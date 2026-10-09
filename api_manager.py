import logging

import httpx
from telegram import Bot
from telegram.error import TelegramError

import config

logger = logging.getLogger(__name__)


class ApiManager:
    def __init__(self) -> None:
        self.public_bot: Bot | None = None
        self.local_bot: Bot | None = None
        self.local_api_available = False
        self.local_url = ""
        self.token = ""
        self.http_client: httpx.AsyncClient | None = None
