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


async def process_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, mode: str) -> None:
    source_message = update.effective_message
    user = update.effective_user
    if source_message is None or user is None:
        return
    chat_id = source_message.chat_id
    source_message_id = source_message.message_id
    await set_reaction(context, chat_id, source_message_id, "👀")
    status_message = await source_message.reply_text("🔍 Fetching info...")
    try:
        if not await asyncio.to_thread(enforce_storage_limit):
            await edit_status(status_message, "⚠️ Server is busy storing files. Try again shortly.")
            await set_reaction(context, chat_id, source_message_id, "❌")
            return
        if await asyncio.to_thread(is_memory_pressure):
            await edit_status(status_message, "⚠️ Server memory is low. Try again shortly.")
            await set_reaction(context, chat_id, source_message_id, "❌")
            return
        cookie_path = await asyncio.to_thread(find_cookie_file, url)
        info = await fetch_metadata(url, cookie_path)
        check_metadata(info)
        sizes = estimate_quality_sizes(info)
        if not sizes and mode != "audio":
            raise FormatUnavailableError()
        request: dict[str, Any] = {
            "url": url,
            "user_id": user.id,
            "title": str(info.get("title") or "video")[:200],
            "duration": int(info.get("duration") or 0),
            "sizes": sizes,
            "chat_id": chat_id,
            "source_message_id": source_message_id,
        }
        if mode == "audio":
            await run_pipeline(context, chat_id, source_message_id, status_message, request, None, True)
        elif mode == "auto":
            resolution, fits = select_auto_format(info)
            note = ""
            if not fits:
                note = (
                    f"⚠️ No quality fits under {api_manager.get_effective_max_mb()} MB. "
                    "Trying the smallest; it may be rejected.\n"
                )
            await run_pipeline(context, chat_id, source_message_id, status_message, request, resolution, False, note)
        else:
            unique_id = uuid.uuid4().hex[:10]
            pending = context.user_data.setdefault("pending", {})
            if len(pending) >= MAX_STORED_REQUESTS:
                pending.pop(next(iter(pending)))
            pending[unique_id] = request
            await edit_status(
                status_message,
                f"🎬 {request['title']}\nChoose a quality:",
                build_quality_keyboard(unique_id, sizes),
            )
    except DownloadError as error:
        await report_failure(
            context, chat_id, source_message_id, status_message, user.id, url, error, mode == "audio"
        )
    except Exception:
        logger.exception("Processing failed for %s", url)
        await edit_status(status_message, "❌ Something went wrong.")
        await set_reaction(context, chat_id, source_message_id, "❌")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or message.text is None or user is None:
        return
    urls = [url for url in extract_urls(message.text) if is_fetchable_url(url)]
    if not urls:
        return
    if len(urls) > config.BATCH_LIMIT:
        await message.reply_text(f"ℹ️ Only processing first {config.BATCH_LIMIT} links.")
        urls = urls[: config.BATCH_LIMIT]
    if await is_cooling_down(message, user.id):
        return
    await asyncio.to_thread(record_user, user.id, user.username)
    mode = "auto" if config.AUTO_QUALITY else "manual"
    for url in urls:
        await process_url(update, context, url, mode)


def find_command_url(message: Message, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    candidates = " ".join(context.args or [])
    if not candidates and message.reply_to_message is not None and message.reply_to_message.text:
        candidates = message.reply_to_message.text
    urls = extract_urls(candidates)
    return urls[0] if urls else None


async def audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    url = find_command_url(message, context)
    if url is None:
        await message.reply_text("Usage: /audio <url> or reply to a message containing a link.")
        return
    if await is_cooling_down(message, user.id):
        return
    await process_url(update, context, url, "audio")


async def quality_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    url = find_command_url(message, context)
    if url is None:
        await message.reply_text("Usage: /quality <url> or reply to a message containing a link.")
        return
    if await is_cooling_down(message, user.id):
        return
    await process_url(update, context, url, "manual")


async def handle_quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or not isinstance(query.message, Message):
        return
    parts = query.data.split(":")
    pending = context.user_data.get("pending", {}) if context.user_data else {}
    request = pending.get(parts[1]) if len(parts) == 3 else None
    if request is None:
        await query.answer("This request expired. Send the link again.", show_alert=True)
        return
    choice = parts[2]
    audio_only = choice == "audio"
    if audio_only:
        size_key = 0
    elif choice.isdigit():
        size_key = int(choice)
    else:
        await query.answer("Invalid quality.", show_alert=True)
        return
    resolution = None if audio_only else size_key
    size_mb = request["sizes"].get(size_key, 0.0)
    limit_mb = api_manager.get_effective_max_mb()
    if size_mb > limit_mb:
        await query.answer(
            f"🔒 This quality is {size_mb:.0f} MB. Max allowed is {limit_mb} MB. "
            "Set up the Local Bot API Server to unlock.",
            show_alert=True,
        )
        return
    pending.pop(parts[1], None)
    await query.answer()
    await run_pipeline(
        context,
        request["chat_id"],
        request["source_message_id"],
        query.message,
        request,
        resolution,
        audio_only,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    temp_mb = await asyncio.to_thread(get_temp_usage_mb)
    stats = await asyncio.to_thread(get_global_stats)
    age_days = await asyncio.to_thread(yt_dlp_age_days)
    if age_days > 30:
        ytdlp_line = f"⚠️ yt-dlp is {age_days} days old. Extractors may be broken; update it."
    else:
        ytdlp_line = f"🧩 yt-dlp: {yt_dlp.version.__version__}"
    lines = [
        "📊 Bot Status",
        "━━━━━━━━━━━━",
        f"{'🟢' if api_manager.public_bot is not None else '🔴'} Public API: "
        f"{'Connected' if api_manager.public_bot is not None else 'Not started'}",
        f"{'🟢' if api_manager.local_api_available else '🔴'} Local API: "
        f"{'Connected' if api_manager.local_api_available else 'Not found'}",
        f"📏 Max file size: {api_manager.get_effective_max_mb()} MB",
        f"💾 Temp storage: {temp_mb:.1f} MB / {config.TEMP_LIMIT_MB} MB",
        f"⬇️ Active downloads: {1 if download_semaphore.locked() else 0}",
        f"📈 Today: {stats['today_downloads']} downloads",
        f"👥 Total users: {stats['total_users']}",
        f"🕐 Uptime: {format_uptime(time.time() - config.START_TIME)}",
        ytdlp_line,
        "🎞 ffmpeg: available" if config.FFMPEG_AVAILABLE else "⚠️ ffmpeg missing: merged formats only",
    ]
    await message.reply_text("\n".join(lines))


async def cookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not is_admin(user.id):
        return
    if not context.args:
        sites = await asyncio.to_thread(list_cookie_sites)
        listing = ", ".join(sites) if sites else "none"
        await message.reply_text(f"🍪 Saved cookie sites: {listing}\nUsage: /cookies <site>")
        return
    site = re.sub(r"[^a-z0-9_-]", "", context.args[0].lower())
    if not site:
        await message.reply_text("❌ Invalid site name.")
        return
    context.user_data["cookie_site"] = site
    await message.reply_text(f"📎 Send the cookies .txt file for {site} now.")


async def cookie_document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or message.document is None or not is_admin(user.id):
        return
    site = context.user_data.pop("cookie_site", None) if context.user_data else None
    if site is None:
        return
    document = message.document
    if document.file_size and document.file_size > COOKIE_UPLOAD_LIMIT_BYTES:
        await message.reply_text("❌ Cookie file is too large.")
        return
    staging_path = os.path.join(config.COOKIES_DIR, f"{site}.upload")
    target_path = os.path.join(config.COOKIES_DIR, f"{site}.txt")
    telegram_file = await document.get_file()
    await telegram_file.download_to_drive(staging_path)
    if not await asyncio.to_thread(is_netscape_cookie_file, staging_path):
        await asyncio.to_thread(delete_file_safe, staging_path)
        await message.reply_text("❌ Not a Netscape cookie file. Export with 'Get cookies.txt LOCALLY'.")
        return
    await asyncio.to_thread(os.replace, staging_path, target_path)
    await message.reply_text(f"✅ Saved cookies for {site}.")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not is_admin(user.id):
        return
    text = " ".join(context.args or []).strip()
    if not text:
        await message.reply_text("Usage: /broadcast <message>")
        return
    user_ids = await asyncio.to_thread(get_all_user_ids)
    sent = 0
    failed = 0
    for target_id in user_ids:
        try:
            await context.bot.send_message(chat_id=target_id, text=text)
            sent += 1
        except TelegramError:
            failed += 1
        await asyncio.sleep(0.05)
    await message.reply_text(f"📣 Broadcast done. Sent: {sent}, failed: {failed}.")
