import asyncio
import glob
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import yt_dlp

import config
from api_manager import api_manager
from cleanup import delete_file_safe
from errors import (
    DownloadError,
    DRMProtectedError,
    DurationExceededError,
    FileTooLargeError,
    FormatUnavailableError,
    LiveStreamError,
    LoginRequiredError,
    MergeFailedError,
    UnknownDownloadError,
    classify_ytdlp_error,
)
from utils import extract_site_name, file_size_megabytes, random_ua

logger = logging.getLogger(__name__)

AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio"


@dataclass(frozen=True)
class DownloadResult:
    file_path: str
    title: str
    duration: int
    site: str
    resolution: int | None
    size_mb: float


def build_format_string(resolution: int | None = None, audio_only: bool = False) -> str:
    if audio_only:
        return AUDIO_FORMAT
    if not config.FFMPEG_AVAILABLE:
        if resolution is None:
            return "best[ext=mp4]/best"
        return f"best[height<={resolution}][ext=mp4]/best[height<={resolution}]"
    if resolution is None:
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    return (
        f"bestvideo[height<={resolution}][ext=mp4]+bestaudio[ext=m4a]/"
        f"best[height<={resolution}][ext=mp4]/"
        f"best[height<={resolution}]"
    )


def find_cookie_file(url: str) -> str | None:
    hostname = (urlparse(url).hostname or "").lower()
    for label in hostname.split("."):
        if not label or label in ("www", "m"):
            continue
        candidate_path = os.path.join(config.COOKIES_DIR, f"{label}.txt")
        if os.path.isfile(candidate_path):
            return candidate_path
    return None


def mark_cookie_stale(cookie_path: str) -> None:
    try:
        os.replace(cookie_path, cookie_path + ".stale")
    except OSError as error:
        logger.error("Could not mark cookie file stale: %s", error)


def is_netscape_cookie_file(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as cookie_file:
            head = cookie_file.read(4096)
    except OSError:
        return False
    return "Netscape HTTP Cookie File" in head or "HTTP Cookie File" in head


def list_cookie_sites() -> list[str]:
    with os.scandir(config.COOKIES_DIR) as entries:
        return sorted(entry.name[:-4] for entry in entries if entry.is_file() and entry.name.endswith(".txt"))


def extract_metadata(url: str, cookie_path: str | None) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 30,
        "extractor_retries": 2,
        "http_headers": {"User-Agent": random_ua()},
    }
    if cookie_path:
        options["cookiefile"] = cookie_path
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=False)


def translate_ytdlp_error(error: Exception, cookie_path: str | None) -> DownloadError:
    translated = classify_ytdlp_error(str(error))
    if isinstance(translated, LoginRequiredError) and cookie_path is not None:
        mark_cookie_stale(cookie_path)
    return translated


async def fetch_metadata(url: str, cookie_path: str | None) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(extract_metadata, url, cookie_path)
    except yt_dlp.utils.YoutubeDLError as error:
        raise (await asyncio.to_thread(translate_ytdlp_error, error, cookie_path)) from error
