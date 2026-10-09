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

    async def health_check(self) -> None:
        was_available = self.local_api_available
        self.local_api_available = await self.probe_local_api()
        if was_available and not self.local_api_available:
            logger.warning("Local API went down. Large files are unavailable until it recovers.")
        elif not was_available and self.local_api_available:
            try:
                await self.create_local_bot()
            except TelegramError as error:
                self.local_api_available = False
                logger.error("Could not initialize local Bot API client: %s", error)
                return
            logger.warning("Local API is back. Large file support re-enabled.")

    def get_effective_max_mb(self) -> int:
        if self.local_api_available:
            return config.MAX_FILE_SIZE_MB
        return min(config.MAX_FILE_SIZE_MB, config.PUBLIC_API_LIMIT_MB)

    def get_sender(self, file_size_mb: float) -> Bot | None:
        if file_size_mb <= config.PUBLIC_API_LIMIT_MB:
            return self.public_bot
        if self.local_api_available and self.local_bot is not None:
            return self.local_bot
        return None

    async def close(self) -> None:
        if self.http_client is not None:
            await self.http_client.aclose()
        for bot in (self.local_bot, self.public_bot):
            if bot is None:
                continue
            try:
                await bot.shutdown()
            except Exception:
                logger.exception("Bot shutdown failed")
