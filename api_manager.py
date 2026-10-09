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

    async def init(self, token: str, local_url: str) -> None:
        self.token = token
        self.local_url = local_url
        self.public_bot = Bot(token=token)
        await self.public_bot.initialize()
        self.http_client = httpx.AsyncClient(timeout=config.PROBE_TIMEOUT_SEC)
        self.local_api_available = await self.probe_local_api()
        if self.local_api_available:
            await self.create_local_bot()
            logger.info("Local API detected. Large file support enabled.")
        elif local_url:
            logger.warning("Local API not found at %s. Files over 50 MB will be rejected.", local_url)

    async def probe_local_api(self) -> bool:
        if not self.local_url or self.http_client is None:
            return False
        try:
            response = await self.http_client.get(
                f"{self.local_url}/bot{self.token}/getMe",
                timeout=config.PROBE_TIMEOUT_SEC,
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def create_local_bot(self) -> None:
        self.local_bot = Bot(token=self.token, base_url=f"{self.local_url}/bot")
        await self.local_bot.initialize()
