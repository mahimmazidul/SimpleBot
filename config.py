import os
import shutil
import time

from dotenv import load_dotenv

load_dotenv()

START_TIME = time.time()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
LOCAL_API_URL = os.getenv("LOCAL_API_URL", "").strip().rstrip("/")
