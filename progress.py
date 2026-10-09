import asyncio
import time
from collections.abc import Coroutine
from datetime import timedelta
from typing import Any

from telegram import Bot
from telegram.error import RetryAfter, TelegramError

from utils import human_duration, human_size
