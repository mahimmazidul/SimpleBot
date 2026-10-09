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
