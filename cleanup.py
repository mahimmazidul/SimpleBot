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
