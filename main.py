import asyncio
import gc
import glob
import logging
import os
import re
import signal
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx
import yt_dlp
from telegram import Bot, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import TelegramError, TimedOut
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

try:
    import uvloop
except ImportError:
    uvloop = None

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN is required. Set it in the environment or in .env.")
LOCAL_API_URL = os.environ.get("LOCAL_API_URL", "").strip().rstrip("/")
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "2000"))
MAX_DURATION_SEC = int(os.environ.get("MAX_DURATION_SEC", "3600"))
TEMP_DIR = os.environ.get("TEMP_DIR", "./temp")
COOKIES_DIR = os.environ.get("COOKIES_DIR", "./cookies")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "ERROR").strip().upper()
ADMIN_IDS = {int(item) for item in os.environ.get("ADMIN_IDS", "").split(",") if item.strip()}

MEGABYTE = 1024 * 1024
PUBLIC_API_LIMIT_MB = 50
TEMP_STORAGE_LIMIT_MB = 1500
USER_COOLDOWN_SECONDS = 5
CLEANUP_INTERVAL_SECONDS = 600
ORPHAN_AGE_SECONDS = 900
PROBE_TIMEOUT_SECONDS = 3
COOKIE_UPLOAD_LIMIT_BYTES = MEGABYTE
MAX_STORED_REQUESTS = 20
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
TRAILING_PUNCTUATION = ".,;:!?)]}"
LOGIN_TERMS = ("login", "sign in", "private", "cookies", "age-restricted", "age restricted")
GEO_TERMS = ("geo", "your country", "your region")
SIZE_TERMS = ("max-filesize", "larger than max")

logging.basicConfig(level=LOG_LEVEL, format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("yt_dlp").setLevel(logging.ERROR)
logger = logging.getLogger("videobot")

download_semaphore = asyncio.Semaphore(1)
local_api_available = False
local_bot: Bot | None = None
user_cooldowns: dict[int, float] = {}
