"""
config.py

Loads all environment variables in one place. See .env.example for what
each setting does.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Environment variable {name} must be an integer, got: {value!r}")


@dataclass(frozen=True)
class Settings:
    google_client_secret_path: str
    google_token_path: str
    database_path: str
    session_end_grace_minutes: int
    scheduler_poll_interval_minutes: int
    drive_recordings_root_folder: str
    recording_check_delay_minutes: int
    recording_check_max_retries: int
    alert_email_to: str
    log_dir: str
    log_level: str
    test_mode: bool


def load_settings() -> Settings:
    required_vars = [
        "GOOGLE_CLIENT_SECRET_PATH",
        "GOOGLE_TOKEN_PATH",
        "DATABASE_PATH",
        "ALERT_EMAIL_TO",
    ]
    missing = [name for name in required_vars if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing) +
            ". Copy .env.example to .env and fill these in."
        )

    return Settings(
        google_client_secret_path=os.environ["GOOGLE_CLIENT_SECRET_PATH"],
        google_token_path=os.environ["GOOGLE_TOKEN_PATH"],
        database_path=os.environ["DATABASE_PATH"],
        session_end_grace_minutes=_get_int("SESSION_END_GRACE_MINUTES", 5),
        scheduler_poll_interval_minutes=_get_int("SCHEDULER_POLL_INTERVAL_MINUTES", 2),
        drive_recordings_root_folder=os.getenv("DRIVE_RECORDINGS_ROOT_FOLDER", "Recordings"),
        recording_check_delay_minutes=_get_int("RECORDING_CHECK_DELAY_MINUTES", 10),
        recording_check_max_retries=_get_int("RECORDING_CHECK_MAX_RETRIES", 6),
        alert_email_to=os.environ["ALERT_EMAIL_TO"],
        log_dir=os.getenv("LOG_DIR", "logs"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        test_mode=os.getenv("TEST_MODE", "true").strip().lower() in ("1", "true", "yes", "on"),
    )


settings = load_settings()
