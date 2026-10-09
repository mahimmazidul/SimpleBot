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


def check_metadata(info: dict[str, Any]) -> None:
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        raise LiveStreamError()
    formats = info.get("formats") or []
    if formats and all(item.get("has_drm") for item in formats):
        raise DRMProtectedError()
    if (info.get("duration") or 0) > config.MAX_DURATION_SEC:
        raise DurationExceededError()


def estimate_bytes(stream: dict[str, Any] | None, duration: float | None) -> float:
    if stream is None:
        return 0.0
    declared_size = stream.get("filesize") or stream.get("filesize_approx")
    if declared_size:
        return float(declared_size)
    bitrate_kbps = stream.get("tbr") or 0
    if bitrate_kbps and duration:
        return bitrate_kbps * 125 * duration
    return 0.0


def estimate_quality_sizes(info: dict[str, Any]) -> dict[int, float]:
    formats = [item for item in info.get("formats") or [] if not item.get("has_drm")]
    duration = info.get("duration")
    videos = [item for item in formats if item.get("vcodec") not in (None, "none") and item.get("height")]
    audios = [
        item
        for item in formats
        if item.get("acodec") not in (None, "none") and item.get("vcodec") in (None, "none")
    ]
    best_audio = max(audios, key=lambda item: item.get("abr") or item.get("tbr") or 0, default=None)
    audio_mb = estimate_bytes(best_audio, duration) / config.MEGABYTE
    sizes: dict[int, float] = {}
    for height in sorted({item["height"] for item in videos}):
        video = max(
            (item for item in videos if item["height"] == height),
            key=lambda item: item.get("tbr") or 0,
        )
        video_mb = estimate_bytes(video, duration) / config.MEGABYTE
        if video.get("acodec") in (None, "none"):
            video_mb += audio_mb
        sizes[height] = video_mb
    if best_audio is not None:
        sizes[0] = audio_mb
    return sizes


def select_auto_format(info: dict[str, Any]) -> tuple[int, bool]:
    sizes = estimate_quality_sizes(info)
    heights = sorted((height for height in sizes if height > 0), reverse=True)
    if not heights:
        raise FormatUnavailableError()
    limit_mb = api_manager.get_effective_max_mb()
    for height in heights:
        if sizes[height] <= limit_mb:
            return height, True
    return heights[-1], False


def build_ydl_options(
    unique_id: str,
    format_string: str,
    cookie_path: str | None,
    progress_hook: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "outtmpl": os.path.join(config.TEMP_DIR, f"{unique_id}.%(ext)s"),
        "format": format_string,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "max_filesize": api_manager.get_effective_max_mb() * config.MEGABYTE,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 5,
        "retry_sleep_functions": {"http": lambda attempt: 2**attempt},
        "concurrent_fragment_downloads": 1,
        "buffersize": 1024,
        "quiet": True,
        "no_warnings": True,
        "http_headers": {"User-Agent": random_ua()},
        "progress_hooks": [progress_hook],
        "nocheckcertificate": False,
        "prefer_insecure": False,
        "ignoreerrors": False,
        "extractor_retries": 2,
        "keepvideo": False,
        "writethumbnail": False,
        "writeinfojson": False,
        "writesubtitles": False,
    }
    if cookie_path:
        options["cookiefile"] = cookie_path
    return options


def run_download_sync(
    url: str,
    unique_id: str,
    format_string: str,
    cookie_path: str | None,
    progress_hook: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    options = build_ydl_options(unique_id, format_string, cookie_path, progress_hook)
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=True)


def find_downloaded_file(unique_id: str) -> str | None:
    candidates = [
        path
        for path in glob.glob(os.path.join(config.TEMP_DIR, f"{unique_id}.*"))
        if not path.endswith((".part", ".ytdl", ".temp"))
    ]
    if not candidates:
        return None
    return max(candidates, key=os.path.getsize)
