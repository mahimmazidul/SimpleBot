import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler

from telegram.ext import Application, ContextTypes

import config
from api_manager import api_manager
from cleanup import cleanup_logs, enforce_storage_limit, periodic_cleanup, startup_cleanup
from database import init_db
from handlers import register_handlers

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    file_handler = RotatingFileHandler(
        os.path.join(config.LOG_DIR, "bot.log"),
        maxBytes=5 * config.MEGABYTE,
        backupCount=3,
        encoding="utf-8",
    )
    stream_handler = logging.StreamHandler()
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.setLevel(config.LOG_LEVEL)
    root_logger.handlers = [file_handler, stream_handler]
    for noisy_name in ("httpx", "telegram", "yt_dlp"):
        logging.getLogger(noisy_name).setLevel(logging.WARNING)
