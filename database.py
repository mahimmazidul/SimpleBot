import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import config

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    site TEXT,
    resolution TEXT,
    file_size_mb REAL,
    duration_sec INTEGER,
    success BOOLEAN,
    error_type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_downloads INTEGER DEFAULT 0
);
"""


def open_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(config.DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def create_schema() -> None:
    with closing(open_connection()) as connection, connection:
        connection.executescript(SCHEMA)


def init_db() -> None:
    try:
        create_schema()
    except sqlite3.DatabaseError as error:
        logger.error("Database unreadable (%s). Recreating it.", error)
        for path in (config.DB_PATH, config.DB_PATH + "-wal", config.DB_PATH + "-shm", config.DB_PATH + "-journal"):
            if os.path.exists(path):
                os.remove(path)
        create_schema()
