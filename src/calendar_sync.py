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
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from src.db import get_session, Batch, ClassSession

logger = logging.getLogger(__name__)


def _extract_meet_link(event: dict) -> Optional[str]:
    if event.get("hangoutLink"):
        return event["hangoutLink"].strip()
    conference_data = event.get("conferenceData", {})
    for entry_point in conference_data.get("entryPoints", []):
        if entry_point.get("entryPointType") == "video" and entry_point.get("uri"):
            return entry_point["uri"].strip()
    return None


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
        link_to_batch = {b.meet_link.strip(): b for b in batches}

        if not link_to_batch:
            logger.warning("No batches found in database — nothing to match calendar events against.")
            return 0

        existing_event_ids = {row.calendar_event_id for row in session.query(ClassSession.calendar_event_id).all()}

        for event in events:
            event_id = event.get("id")
            if not event_id or event_id in existing_event_ids:
                continue

            meet_link = _extract_meet_link(event)
            if not meet_link or meet_link not in link_to_batch:
                continue

            start_dt = _parse_event_datetime(event.get("start", {}))
            end_dt = _parse_event_datetime(event.get("end", {}))
            if not start_dt or not end_dt:
                continue

            batch = link_to_batch[meet_link]
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
