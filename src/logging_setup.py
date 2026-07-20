"""
logging_setup.py

Sets up file-based logging (logs/system.log, rotating) plus console output,
so a crash or missed recording can be diagnosed after the fact.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from src.config import settings


def setup_logging() -> None:
    os.makedirs(settings.log_dir, exist_ok=True)

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_path = os.path.join(settings.log_dir, "system.log")
    file_handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = []
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.getLogger(__name__).info(
        "Logging initialized. system.log -> %s | level=%s", log_path, settings.log_level
    )
