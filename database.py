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


def record_user(user_id: int, username: str | None) -> None:
    with closing(open_connection()) as connection, connection:
        connection.execute(
            """
            INSERT INTO users (user_id, username, first_seen, last_active, total_downloads)
            VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                last_active = CURRENT_TIMESTAMP
            """,
            (user_id, username),
        )


def record_download(
    user_id: int,
    url: str,
    site: str | None,
    resolution: str | None,
    file_size_mb: float | None,
    duration_sec: int | None,
    success: bool,
    error_type: str | None,
) -> None:
    with closing(open_connection()) as connection, connection:
        connection.execute(
            """
            INSERT INTO downloads (user_id, url, site, resolution, file_size_mb, duration_sec, success, error_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, url, site, resolution, file_size_mb, duration_sec, int(success), error_type),
        )
        if success:
            connection.execute(
                "UPDATE users SET total_downloads = total_downloads + 1, last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,),
            )


def get_user_stats(user_id: int) -> dict[str, Any]:
    with closing(open_connection()) as connection:
        totals = connection.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(file_size_mb), 0) AS total_mb "
            "FROM downloads WHERE user_id = ? AND success = 1",
            (user_id,),
        ).fetchone()
        favorite = connection.execute(
            "SELECT site FROM downloads WHERE user_id = ? AND success = 1 AND site IS NOT NULL "
            "GROUP BY site ORDER BY COUNT(*) DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return {
        "total_downloads": totals["total"],
        "total_gb": totals["total_mb"] / 1024,
        "favorite_site": favorite["site"] if favorite else None,
    }


def utc_start_of_today() -> str:
    local_now = datetime.now(ZoneInfo(config.DISPLAY_TIMEZONE))
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
