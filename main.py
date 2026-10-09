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
