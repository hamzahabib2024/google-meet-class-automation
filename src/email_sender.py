"""
email_sender.py

Only job now: send an alert email if a recording never appears. All the
reminder-email logic from the original scope was removed since students
are already handled via calendar guests.
"""

import base64
import logging
from email.mime.text import MIMEText

from src.config import settings

logger = logging.getLogger(__name__)


def send_email(gmail_service, to_email: str, subject: str, body_text: str) -> None:
    message = MIMEText(body_text)
    message["to"] = to_email
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    gmail_service.users().messages().send(userId="me", body={"raw": raw}).execute()


def send_alert(gmail_service, subject: str, body_text: str) -> None:
    """Failures here are logged CRITICAL but swallowed — must never crash the scheduler."""
    try:
        send_email(gmail_service, settings.alert_email_to, subject, body_text)
        logger.info("Alert sent to %s: %s", settings.alert_email_to, subject)
    except Exception as exc:
        logger.critical(
            "FAILED TO SEND ALERT EMAIL to %s (subject: %s). Error: %s.",
            settings.alert_email_to, subject, exc,
        )
