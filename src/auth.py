"""
auth.py

Google OAuth via the "Desktop app" Client ID/Secret flow. First run opens
a browser for a one-time login; every run after that refreshes silently.
"""

import os
import logging

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from src.config import settings

logger = logging.getLogger(__name__)

# Only what this scoped-down project actually uses:
# - Calendar: read class schedule
# - Meet: read/manage the space (resolve id, end active conference)
# - Drive: move recordings into batch folders
# - Gmail: send alert emails if a recording never appears
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/meetings.space.created",
    "https://www.googleapis.com/auth/meetings.space.readonly",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
]


def get_credentials() -> Credentials:
    client_secret_path = settings.google_client_secret_path
    token_path = settings.google_token_path

    if not os.path.exists(client_secret_path):
        raise FileNotFoundError(
            f"client_secret.json not found at '{client_secret_path}'. "
            "See README.md for setup instructions."
        )

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Access token expired — refreshing silently.")
            creds.refresh(Request())
        else:
            logger.info("No valid token found — opening browser for one-time login.")
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            # Force Google's account chooser so a browser with multiple signed-in
            # accounts does not silently authorize the wrong account.
            creds = flow.run_local_server(port=0, prompt="select_account")

        _save_token(creds, token_path)

    return creds


def _save_token(creds: Credentials, token_path: str) -> None:
    token_dir = os.path.dirname(token_path)
    if token_dir and not os.path.exists(token_dir):
        os.makedirs(token_dir, exist_ok=True)
    with open(token_path, "w") as token_file:
        token_file.write(creds.to_json())
    logger.debug("Saved credentials to %s", token_path)
