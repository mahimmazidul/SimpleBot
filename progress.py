import asyncio
import time
from collections.abc import Coroutine
from datetime import timedelta
from typing import Any

from telegram import Bot
from telegram.error import RetryAfter, TelegramError

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
