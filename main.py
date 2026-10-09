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
