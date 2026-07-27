"""
calendar_sync.py

Reads upcoming/recent events from Google Calendar and matches each one to
a batch by comparing the event's Meet link against Batch.meet_link (not by
title, since titles can be inconsistent but the permanent link can't be).
For every match, a ClassSession row is created if one doesn't already exist.

Usage:
    from googleapiclient.discovery import build
    from src.auth import get_credentials
    from src.calendar_sync import sync_recent_and_upcoming_sessions

    creds = get_credentials()
    calendar_service = build("calendar", "v3", credentials=creds)
    sync_recent_and_upcoming_sessions(calendar_service)
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from src.db import get_session, Batch, ClassSession

logger = logging.getLogger(__name__)

_MEETING_CODE_RE = re.compile(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", re.IGNORECASE)


def _extract_meet_link(event: dict) -> Optional[str]:
    if event.get("hangoutLink"):
        return event["hangoutLink"].strip()
    conference_data = event.get("conferenceData", {})
    for entry_point in conference_data.get("entryPoints", []):
        if entry_point.get("entryPointType") == "video" and entry_point.get("uri"):
            return entry_point["uri"].strip()
    return None


def _extract_meeting_code(meet_link: str) -> Optional[str]:
    """Pulls just the abc-defg-hij code out of a Meet URL, ignoring scheme,
    trailing slashes, and query params so links only need to match on the
    part that actually identifies the space."""
    match = _MEETING_CODE_RE.search(meet_link or "")
    return match.group(1).lower() if match else None


def _parse_event_datetime(event_time: dict) -> Optional[datetime]:
    if "dateTime" in event_time:
        return datetime.fromisoformat(event_time["dateTime"])
    return None  # all-day event — not a class


def fetch_events(calendar_service, hours_back: int = 24, hours_ahead: int = 48, calendar_id: str = "primary") -> List[dict]:
    """
    Fetches events in a window around now: some hours back (to catch
    classes that already happened, so we can still file their recordings)
    through some hours ahead (to know what's coming).
    """
    now = datetime.now(timezone.utc)
    time_min = now - timedelta(hours=hours_back)
    time_max = now + timedelta(hours=hours_ahead)

    events_result = (
        calendar_service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events = events_result.get("items", [])
    logger.debug("Fetched %d calendar event(s)", len(events))
    return events


def sync_recent_and_upcoming_sessions(calendar_service, hours_back: int = 24, hours_ahead: int = 48, calendar_id: str = "primary") -> int:
    """
    Matches calendar events to batches by Meet link and creates a
    ClassSession for any match not already tracked. Returns the count of
    newly created sessions.
    """
    events = fetch_events(calendar_service, hours_back, hours_ahead, calendar_id)
    created_count = 0

    with get_session() as session:
        batches = session.query(Batch).all()
        code_to_batch = {}
        for b in batches:
            code = _extract_meeting_code(b.meet_link)
            if code:
                code_to_batch[code] = b
            else:
                logger.warning("Batch '%s' has an unparseable Meet link '%s' — it will never match calendar events.", b.section_name, b.meet_link)

        if not code_to_batch:
            logger.warning("No batches with a parseable Meet link found — nothing to match calendar events against.")
            return 0

        existing_event_ids = {row.calendar_event_id for row in session.query(ClassSession.calendar_event_id).all()}

        for event in events:
            event_id = event.get("id")
            if not event_id or event_id in existing_event_ids:
                continue

            meet_link = _extract_meet_link(event)
            meeting_code = _extract_meeting_code(meet_link) if meet_link else None
            if not meeting_code or meeting_code not in code_to_batch:
                continue

            start_dt = _parse_event_datetime(event.get("start", {}))
            end_dt = _parse_event_datetime(event.get("end", {}))
            if not start_dt or not end_dt:
                continue

            batch = code_to_batch[meeting_code]
            session.add(ClassSession(
                batch_id=batch.id,
                calendar_event_id=event_id,
                scheduled_start=start_dt.astimezone(timezone.utc).replace(tzinfo=None),
                scheduled_end=end_dt.astimezone(timezone.utc).replace(tzinfo=None),
            ))
            created_count += 1
            logger.info("New class session for batch '%s': %s -> %s", batch.section_name, start_dt, end_dt)

    if created_count:
        logger.info("Calendar sync created %d new class session(s).", created_count)
    return created_count
