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


def ensure_directories() -> None:
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(COOKIES_DIR, exist_ok=True)


def delete_file_quietly(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as error:
        logger.error("Could not delete %s: %s", path, error)
    gc.collect()


def wipe_temp_directory() -> None:
    with os.scandir(TEMP_DIR) as entries:
        stale_paths = [entry.path for entry in entries if entry.is_file() and not entry.name.startswith(".")]
    for stale_path in stale_paths:
        delete_file_quietly(stale_path)


def delete_downloads_for(unique_id: str) -> None:
    for path in glob.glob(os.path.join(TEMP_DIR, f"{unique_id}*")):
        delete_file_quietly(path)


def temp_usage_megabytes() -> float:
    with os.scandir(TEMP_DIR) as entries:
        total_bytes = sum(entry.stat().st_size for entry in entries if entry.is_file())
    return total_bytes / MEGABYTE


def file_size_megabytes(file_path: str) -> float:
    return os.path.getsize(file_path) / MEGABYTE


def cleanup_stale_temp_files(max_age_seconds: int) -> int:
    cutoff = time.time() - max_age_seconds
    with os.scandir(TEMP_DIR) as entries:
        stale_paths = [entry.path for entry in entries if entry.is_file() and entry.stat().st_mtime < cutoff]
    for stale_path in stale_paths:
        delete_file_quietly(stale_path)
    return len(stale_paths)


async def periodic_cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    removed_count = await asyncio.to_thread(cleanup_stale_temp_files, ORPHAN_AGE_SECONDS)
    if removed_count:
        logger.info("Removed %d stale temp files.", removed_count)


def extract_urls(text: str) -> list[str]:
    return [match.rstrip(TRAILING_PUNCTUATION) for match in URL_PATTERN.findall(text)]


def check_user_cooldown(user_id: int) -> float:
    now = time.monotonic()
    last_seen = user_cooldowns.get(user_id)
    if last_seen is not None and now - last_seen < USER_COOLDOWN_SECONDS:
        return USER_COOLDOWN_SECONDS - (now - last_seen)
    user_cooldowns[user_id] = now
    return 0.0
