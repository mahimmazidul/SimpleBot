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
