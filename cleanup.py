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
