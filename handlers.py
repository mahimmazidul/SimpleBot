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


async def build_start_text() -> str:
    stats = await asyncio.to_thread(get_global_stats)
    return START_TEMPLATE.format(
        local_api_status_line=local_status_line(),
        today_stats_line=f"📈 Today: {stats['today_downloads']} downloads",
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    await message.reply_text(await build_start_text())


async def record_outcome(
    user_id: int,
    url: str,
    site: str | None,
    resolution: str | None,
    size_mb: float | None,
    duration: int | None,
    success: bool,
    error_type: str | None,
) -> None:
    try:
        await asyncio.to_thread(record_download, user_id, url, site, resolution, size_mb, duration, success, error_type)
    except Exception:
        logger.exception("Could not record download statistics")


def make_quality_button(label: str, size_mb: float, limit_mb: int, callback_data: str) -> InlineKeyboardButton:
    size_text = f" ~{size_mb:.0f}MB" if size_mb > 0 else ""
    lock_text = " 🔒" if size_mb > limit_mb else ""
    return InlineKeyboardButton(f"{label}{size_text}{lock_text}", callback_data=callback_data)


def build_quality_keyboard(unique_id: str, sizes: dict[int, float]) -> InlineKeyboardMarkup:
    limit_mb = api_manager.get_effective_max_mb()
    buttons: list[InlineKeyboardButton] = []
    heights = sorted((height for height in sizes if height > 0), reverse=True)[:4]
    for height in heights:
        buttons.append(make_quality_button(f"{height}p", sizes[height], limit_mb, f"quality:{unique_id}:{height}"))
    if 0 in sizes:
        buttons.append(make_quality_button("Audio", sizes[0], limit_mb, f"quality:{unique_id}:audio"))
    rows = [buttons[start : start + 2] for start in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def resolution_label(audio_only: bool, resolution: int | None) -> str | None:
    if audio_only:
        return "Audio"
    return f"{resolution}p" if resolution else None


async def report_failure(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    source_message_id: int,
    status_message: Message,
    user_id: int,
    url: str,
    error: DownloadError,
    audio_only: bool,
) -> None:
    await edit_status(status_message, error.user_message)
    await set_reaction(context, chat_id, source_message_id, "❌")
    await record_outcome(
        user_id,
        url,
        extract_site_name(url),
        resolution_label(audio_only, None),
        None,
        None,
        False,
        type(error).__name__,
    )


async def send_result(chat_id: int, result: DownloadResult, audio_only: bool) -> None:
    sender = api_manager.get_sender(result.size_mb)
    if sender is None:
        raise FileTooLargeError(size_mb=result.size_mb, limit_mb=api_manager.get_effective_max_mb())
    caption = format_caption(
        result.title,
        result.site,
        resolution_label(audio_only, result.resolution),
        result.duration,
        result.size_mb,
    )
    for attempt in range(2):
        try:
            with open(result.file_path, "rb") as media_file:
                if audio_only:
                    await sender.send_audio(
                        chat_id=chat_id,
                        audio=media_file,
                        title=result.title[:64],
                        duration=result.duration or None,
                        caption=caption,
                        read_timeout=300,
                        write_timeout=300,
                    )
                else:
                    await sender.send_video(
                        chat_id=chat_id,
                        video=media_file,
                        caption=caption,
                        duration=result.duration or None,
                        supports_streaming=True,
                        read_timeout=300,
                        write_timeout=300,
                    )
            return
        except TimedOut:
            if attempt == 1:
                raise


async def run_pipeline(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    source_message_id: int,
    status_message: Message,
    request: dict[str, Any],
    resolution: int | None,
    audio_only: bool,
    note: str = "",
) -> None:
    unique_id = uuid.uuid4().hex[:10]
    cookie_path = await asyncio.to_thread(find_cookie_file, request["url"])
    try:
        if download_semaphore.locked():
            await edit_status(status_message, f"{note}⏳ Queued. Another download is in progress...")
        async with download_semaphore:
            await edit_status(status_message, f"{note}⬇️ Starting download...")
            progress = ProgressTracker(context.bot, status_message.chat_id, status_message.message_id)
            result = await download_media(
                request["url"], unique_id, resolution, audio_only, cookie_path, progress.hook
            )
        await edit_status(status_message, "📤 Uploading...")
        await send_result(chat_id, result, audio_only)
        try:
            await status_message.delete()
        except TelegramError:
            pass
        await record_outcome(
            request["user_id"],
            request["url"],
            result.site,
            resolution_label(audio_only, result.resolution),
            result.size_mb,
            result.duration,
            True,
            None,
        )
        await set_reaction(context, chat_id, source_message_id, "✅")
    except DownloadError as error:
        await report_failure(
            context, chat_id, source_message_id, status_message, request["user_id"], request["url"], error, audio_only
        )
    except TimedOut:
        await edit_status(status_message, "❌ Upload timed out.")
        await set_reaction(context, chat_id, source_message_id, "❌")
    except TelegramError as error:
        logger.error("Telegram send failed: %s", error)
        await edit_status(status_message, "❌ Telegram upload failed.")
        await set_reaction(context, chat_id, source_message_id, "❌")
    except Exception:
        logger.exception("Download failed for %s", request["url"])
        await edit_status(status_message, "❌ Something went wrong.")
        await set_reaction(context, chat_id, source_message_id, "❌")
    finally:
        await asyncio.to_thread(cleanup_by_id, unique_id)
