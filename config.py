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
