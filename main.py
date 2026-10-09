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


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def effective_max_megabytes() -> int:
    if local_api_available:
        return MAX_FILE_SIZE_MB
    return min(MAX_FILE_SIZE_MB, PUBLIC_API_LIMIT_MB)


def estimate_stream_bytes(stream: dict[str, Any] | None, duration: float | None) -> float:
    if stream is None:
        return 0.0
    declared_size = stream.get("filesize") or stream.get("filesize_approx")
    if declared_size:
        return float(declared_size)
    bitrate_kbps = stream.get("tbr") or 0
    if bitrate_kbps and duration:
        return bitrate_kbps * 125 * duration
    return 0.0


def fetch_video_information(url: str, cookie_path: str | None) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 30,
    }
    if cookie_path:
        options["cookiefile"] = cookie_path
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=False)


def build_quality_tiers(info: dict[str, Any]) -> list[dict[str, Any]]:
    formats = info.get("formats") or []
    duration = info.get("duration")
    videos = [item for item in formats if item.get("vcodec") not in (None, "none") and item.get("height")]
    audios = [
        item
        for item in formats
        if item.get("acodec") not in (None, "none") and item.get("vcodec") in (None, "none")
    ]
    best_audio = max(audios, key=lambda item: item.get("abr") or item.get("tbr") or 0, default=None)
    audio_bytes = estimate_stream_bytes(best_audio, duration)
    tiers: list[dict[str, Any]] = []
    seen_heights: set[int] = set()
    for height_limit in (None, 720, 480, 360):
        candidates = [item for item in videos if height_limit is None or item["height"] <= height_limit]
        if not candidates:
            continue
        video = max(candidates, key=lambda item: (item["height"], item.get("tbr") or 0))
        if video["height"] in seen_heights:
            continue
        seen_heights.add(video["height"])
        size_bytes = estimate_stream_bytes(video, duration)
        if video.get("acodec") in (None, "none"):
            size_bytes += audio_bytes
        if height_limit is None:
            selector = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
        else:
            selector = (
                f"bestvideo[height<={height_limit}][ext=mp4]+bestaudio[ext=m4a]/"
                f"bestvideo[height<={height_limit}]+bestaudio/best[height<={height_limit}]"
            )
        tiers.append(
            {
                "title": f"{video['height']}p",
                "size_mb": size_bytes / MEGABYTE,
                "format": selector,
                "is_audio": False,
            }
        )
    if best_audio is not None:
        tiers.append(
            {
                "title": "Audio",
                "size_mb": audio_bytes / MEGABYTE,
                "format": "bestaudio[ext=m4a]/bestaudio",
                "is_audio": True,
            }
        )
    return tiers


def build_keyboard(token: str, tiers: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    limit_mb = effective_max_megabytes()
    buttons: list[InlineKeyboardButton] = []
    for index, tier in enumerate(tiers):
        size_text = f" ~{tier['size_mb']:.0f}MB" if tier["size_mb"] > 0 else ""
        lock_text = " 🔒" if tier["size_mb"] > limit_mb else ""
        buttons.append(
            InlineKeyboardButton(f"{tier['title']}{size_text}{lock_text}", callback_data=f"dl|{token}|{index}")
        )
    rows = [buttons[start : start + 2] for start in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def find_cookie_file(url: str) -> str | None:
    hostname = (urlparse(url).hostname or "").lower()
    for label in hostname.split("."):
        if not label or label in ("www", "m"):
            continue
        candidate_path = os.path.join(COOKIES_DIR, f"{label}.txt")
        if os.path.isfile(candidate_path):
            return candidate_path
    return None


def build_download_options(unique_id: str, format_selector: str, cookie_path: str | None) -> dict[str, Any]:
    options: dict[str, Any] = {
        "outtmpl": os.path.join(TEMP_DIR, f"{unique_id}.%(ext)s"),
        "format": format_selector,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "concurrent_fragment_downloads": 1,
        "buffersize": 1024,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "max_filesize": effective_max_megabytes() * MEGABYTE,
        "writethumbnail": False,
        "writeinfojson": False,
        "writesubtitles": False,
        "writedescription": False,
        "keepvideo": False,
    }
    if cookie_path:
        options["cookiefile"] = cookie_path
    return options


def download_media(url: str, unique_id: str, format_selector: str, cookie_path: str | None) -> dict[str, Any]:
    options = build_download_options(unique_id, format_selector, cookie_path)
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=True)
