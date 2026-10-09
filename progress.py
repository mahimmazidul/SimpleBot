import asyncio
import time
from collections.abc import Coroutine
from datetime import timedelta
from typing import Any

from telegram import Bot
from telegram.error import RetryAfter, TelegramError

import messages as msg
from messages import render
from utils import human_duration, human_size


class ProgressTracker:
    def __init__(self, bot: Bot, chat_id: int, message_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.loop = asyncio.get_running_loop()
        self.last_edit_time = 0.0
        self.blocked_until = 0.0
        self.last_percentage = -1

    def hook(self, data: dict[str, Any]) -> None:
        status = data.get("status")
        if status == "finished":
            self.schedule(self.edit_text(msg.PROCESSING))
            return
        if status != "downloading":
            return
        total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
        if total <= 0:
            return
        downloaded = data.get("downloaded_bytes") or 0
        percentage = min(100, int(downloaded * 100 / total))
        if percentage == self.last_percentage:
            return
        now = time.time()
        if now - self.last_edit_time < 3 or now < self.blocked_until:
            return
        self.last_edit_time = now
        self.last_percentage = percentage
        speed = data.get("speed") or 0
        eta = data.get("eta") or 0
        filled = percentage // 10
        bar = msg.BAR_FILLED * filled + msg.BAR_EMPTY * (10 - filled)
        eta_text = msg.ETA_LINE.format(eta=human_duration(eta)) if eta else ""
        text = msg.PROGRESS_LINE.format(
            bar=bar,
            percentage=percentage,
            downloaded=human_size(downloaded),
            total=human_size(total),
            speed=human_size(speed),
            eta=eta_text,
        )
        self.schedule(self.edit_text(text))

    def schedule(self, coroutine: Coroutine[Any, Any, None]) -> None:
        asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    async def edit_text(self, text: str) -> None:
        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=render(text),
            )
        except RetryAfter as error:
            retry_seconds = (
                error.retry_after.total_seconds()
                if isinstance(error.retry_after, timedelta)
                else float(error.retry_after)
            )
            self.blocked_until = time.time() + retry_seconds
        except TelegramError:
            pass
