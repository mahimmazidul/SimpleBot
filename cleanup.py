import gc
import glob
import logging
import os
import time

import config

logger = logging.getLogger(__name__)


def delete_file_safe(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as error:
        logger.error("Could not delete %s: %s", path, error)
    gc.collect()


def cleanup_by_id(unique_id: str) -> None:
    for path in glob.glob(os.path.join(config.TEMP_DIR, f"{unique_id}*")):
        delete_file_safe(path)


def get_temp_usage_mb() -> float:
    with os.scandir(config.TEMP_DIR) as entries:
        total_bytes = sum(entry.stat().st_size for entry in entries if entry.is_file())
    return total_bytes / config.MEGABYTE


def startup_cleanup() -> None:
    with os.scandir(config.TEMP_DIR) as entries:
        stale_paths = [entry.path for entry in entries if entry.is_file() and not entry.name.startswith(".")]
    for path in stale_paths:
        delete_file_safe(path)


def periodic_cleanup(max_age_sec: int = 900) -> int:
    cutoff = time.time() - max_age_sec
    with os.scandir(config.TEMP_DIR) as entries:
        stale_paths = [entry.path for entry in entries if entry.is_file() and entry.stat().st_mtime < cutoff]
    for path in stale_paths:
        delete_file_safe(path)
    return len(stale_paths)


def enforce_storage_limit() -> bool:
    if get_temp_usage_mb() <= config.TEMP_LIMIT_MB:
        return True
    periodic_cleanup(60)
    return get_temp_usage_mb() <= config.TEMP_LIMIT_MB


def cleanup_logs(max_age_days: int = 7) -> int:
    cutoff = time.time() - max_age_days * 86400
    with os.scandir(config.LOG_DIR) as entries:
        stale_paths = [
            entry.path
            for entry in entries
            if entry.is_file() and entry.name != "bot.log" and entry.stat().st_mtime < cutoff
        ]
    for path in stale_paths:
        delete_file_safe(path)
    return len(stale_paths)
