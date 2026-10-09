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
