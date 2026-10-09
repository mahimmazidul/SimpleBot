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


async def post_init(application: Application) -> None:
    await asyncio.to_thread(init_db)
    await asyncio.to_thread(startup_cleanup)
    await api_manager.init(config.BOT_TOKEN, config.LOCAL_API_URL)
    if not config.FFMPEG_AVAILABLE:
        logger.warning("ffmpeg not found. Using pre-merged formats only.")
    logger.info("Bot started.")


async def post_shutdown(application: Application) -> None:
    await asyncio.to_thread(periodic_cleanup, 0)
    await api_manager.close()
    logger.info("Bot shut down cleanly.")


async def periodic_cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await asyncio.to_thread(periodic_cleanup, 900)
    await asyncio.to_thread(cleanup_logs)


async def storage_guard_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    within_limit = await asyncio.to_thread(enforce_storage_limit)
    if not within_limit:
        logger.warning("Temp storage remains above limit after cleanup.")


async def api_health_check_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await api_manager.health_check()


def main() -> None:
    config.validate()
    setup_logging()
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .concurrent_updates(2)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    register_handlers(application)
    application.job_queue.run_repeating(periodic_cleanup_job, interval=600, first=60)
    application.job_queue.run_repeating(storage_guard_job, interval=120, first=30)
    if config.LOCAL_API_URL:
        application.job_queue.run_repeating(api_health_check_job, interval=300, first=120)
    application.run_polling(drop_pending_updates=True, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
