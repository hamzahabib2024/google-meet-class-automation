"""
main.py

Entry point. Run with: python -m src.main

1. Sets up logging.
2. Initializes the database.
3. Authenticates with Google (browser login on first run only).
4. Builds Calendar, Meet, Drive, Gmail (alerts only) service clients.
5. Reconciles against the calendar.
6. Starts the scheduler, which runs forever: closes rooms after class,
   files recordings into the right batch folder.

Press Ctrl+C to stop.
"""

import logging
import time
import sys

from googleapiclient.discovery import build

from src.logging_setup import setup_logging
from src.config import settings
from src.db import init_db
from src.auth import get_credentials
from src.scheduler import build_scheduler, reconcile_on_startup

logger = logging.getLogger(__name__)


def build_services(creds):
    calendar_service = build("calendar", "v3", credentials=creds)
    meet_service = build("meet", "v2", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)
    gmail_service = build("gmail", "v1", credentials=creds)
    return calendar_service, meet_service, drive_service, gmail_service


def main() -> None:
    setup_logging()

    logger.info("=" * 60)
    logger.info("Recording Automation starting up")
    logger.info("TEST_MODE = %s", settings.test_mode)
    if settings.test_mode:
        logger.warning("Running in TEST MODE. Make sure .env points at a test database and test batch.")
    logger.info("=" * 60)

    try:
        init_db()
    except Exception as exc:
        logger.critical("Failed to initialize database: %s", exc)
        sys.exit(1)

    try:
        creds = get_credentials()
    except FileNotFoundError as exc:
        logger.critical(str(exc))
        sys.exit(1)
    except Exception as exc:
        logger.critical("Google authentication failed: %s", exc)
        sys.exit(1)

    try:
        calendar_service, meet_service, drive_service, gmail_service = build_services(creds)
    except Exception as exc:
        logger.critical("Failed to build Google API service clients: %s", exc)
        sys.exit(1)

    reconcile_on_startup(calendar_service)

    scheduler = build_scheduler(calendar_service, meet_service, drive_service, gmail_service)
    scheduler.start()
    logger.info(
        "Scheduler started — checking every %d minute(s). Press Ctrl+C to stop.",
        settings.scheduler_poll_interval_minutes,
    )

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested — stopping scheduler...")
        scheduler.shutdown(wait=False)
        logger.info("Stopped cleanly.")


if __name__ == "__main__":
    main()
