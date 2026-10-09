import asyncio
import logging
import os
import re
import time
import uuid
from typing import Any

import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import TelegramError, TimedOut
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import config
from api_manager import api_manager
from cleanup import cleanup_by_id, delete_file_safe, enforce_storage_limit, get_temp_usage_mb
from database import get_all_user_ids, get_detailed_stats, get_global_stats, record_download, record_user
from downloader import (
    DownloadResult,
    check_metadata,
    download_media,
    estimate_quality_sizes,
    fetch_metadata,
    find_cookie_file,
    is_netscape_cookie_file,
    list_cookie_sites,
    select_auto_format,
)
from errors import DownloadError, FileTooLargeError, FormatUnavailableError
from progress import ProgressTracker
from utils import (
    extract_site_name,
    extract_urls,
    format_caption,
    format_uptime,
    is_admin,
    is_fetchable_url,
    is_memory_pressure,
    yt_dlp_age_days,
)

logger = logging.getLogger(__name__)


COOKIE_UPLOAD_LIMIT_BYTES = 1024 * 1024
MAX_STORED_REQUESTS = 20
START_TEMPLATE = (
    "🎬 Send me a video link from any site.\n\n"
    "I'll auto-pick the best quality that fits.\n\n"
    "Commands:\n"
    "/audio <url> — audio only\n"
    "/quality <url> — pick quality manually\n"
    "/status — bot status\n"
    "/help — this message\n\n"
    "{local_api_status_line}\n"
    "{today_stats_line}"
)


download_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT)
user_last_request: dict[int, float] = {}


def check_cooldown(user_id: int) -> float:
    now = time.monotonic()
    last_seen = user_last_request.get(user_id)
    if last_seen is not None and now - last_seen < config.USER_COOLDOWN_SEC:
        return config.USER_COOLDOWN_SEC - (now - last_seen)
    user_last_request[user_id] = now
    return 0.0


async def is_cooling_down(message: Message, user_id: int) -> bool:
    remaining = check_cooldown(user_id)
    if remaining > 0:
        await message.reply_text(f"⏳ Wait {remaining:.0f}s before the next request.")
        return True
    return False


async def set_reaction(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, emoji: str) -> None:
    try:
        await context.bot.set_message_reaction(chat_id=chat_id, message_id=message_id, reaction=emoji)
    except TelegramError:
        pass


async def edit_status(
    message: Message | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if not isinstance(message, Message):
        return
    try:
        await message.edit_text(text[:4000], reply_markup=reply_markup)
    except TelegramError as error:
        logger.error("Status edit failed: %s", error)


def local_status_line() -> str:
    if api_manager.local_api_available:
        return f"✅ Large file support active (up to {api_manager.get_effective_max_mb()} MB)"
    return "⚠️ Large files unavailable. Max 50 MB. Ask admin to set up Local API."
