import os
import shutil
import time

from dotenv import load_dotenv

load_dotenv()

START_TIME = time.time()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
LOCAL_API_URL = os.getenv("LOCAL_API_URL", "").strip().rstrip("/")

MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "2000"))
MAX_DURATION_SEC = int(os.getenv("MAX_DURATION_SEC", "3600"))
TEMP_DIR = os.getenv("TEMP_DIR", "./temp")
COOKIES_DIR = os.getenv("COOKIES_DIR", "./cookies")
LOG_DIR = os.getenv("LOG_DIR", "./logs")
LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING").strip().upper()
DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
TEMP_LIMIT_MB = int(os.getenv("TEMP_LIMIT_MB", "1500"))

ADMIN_IDS = frozenset(int(item) for item in os.getenv("ADMIN_IDS", "").split(",") if item.strip())
USER_COOLDOWN_SEC = int(os.getenv("USER_COOLDOWN_SEC", "5"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "1"))
AUTO_QUALITY = os.getenv("AUTO_QUALITY", "true").strip().lower() in ("1", "true", "yes", "on")
BATCH_LIMIT = int(os.getenv("BATCH_LIMIT", "3"))

MEGABYTE = 1024 * 1024
PUBLIC_API_LIMIT_MB = 50
PROBE_TIMEOUT_SEC = 3
MEMORY_PRESSURE_MB = 150
DISPLAY_TIMEZONE = "Asia/Dhaka"

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def validate() -> None:
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is required. Set it in .env or the environment.")
    for directory in (TEMP_DIR, COOKIES_DIR, LOG_DIR):
        os.makedirs(directory, exist_ok=True)
    parent = os.path.dirname(os.path.abspath(DB_PATH))
    os.makedirs(parent, exist_ok=True)
