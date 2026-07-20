"""
scheduler.py

The orchestrator, trimmed to two jobs per class:
  1. Close the Meet session after class end + grace period.
  2. Retry filing the recording until it's found (or retries run out).

On startup, reconciles against the calendar first so a restart doesn't
lose track of a class that happened while the process was down.
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from src.config import settings
from src.db import get_session, ClassSession, Batch
from src.calendar_sync import sync_recent_and_upcoming_sessions
from src.meet_utils import resolve_space_id, close_session
from src.email_sender import send_alert
from src.drive_recording import try_file_recording_for_session

logger = logging.getLogger(__name__)

_recording_retry_counts: dict[int, int] = {}


def reconcile_on_startup(calendar_service) -> None:
    logger.info("Startup reconciliation: syncing calendar...")
    try:
        new_sessions = sync_recent_and_upcoming_sessions(calendar_service)
        logger.info("Startup reconciliation: %d new class session(s) found.", new_sessions)
    except Exception as exc:
        logger.error("Startup calendar sync failed: %s", exc)


def _process_session_close(meet_service) -> None:
    now = datetime.utcnow()
    close_threshold = now - timedelta(minutes=settings.session_end_grace_minutes)
    lookback_threshold = now - timedelta(hours=6)

    with get_session() as session:
        due = session.query(ClassSession).filter(
            ClassSession.session_closed == False,  # noqa: E712
            ClassSession.scheduled_end <= close_threshold,
            ClassSession.scheduled_end > lookback_threshold,
        ).all()
        due_items = [(cs.id, cs.batch_id) for cs in due]

    for session_id, batch_id in due_items:
        with get_session() as session:
            batch = session.query(Batch).filter_by(id=batch_id).one()
            batch_name = batch.section_name

        with get_session() as session:
            batch = session.query(Batch).filter_by(id=batch_id).one()
            space_id = resolve_space_id(meet_service, batch)

        if not space_id:
            logger.warning("Cannot close session %s — batch '%s' has no resolvable space id yet.", session_id, batch_name)
            continue

        if close_session(meet_service, space_id, batch_name):
            with get_session() as session:
                cs = session.query(ClassSession).filter_by(id=session_id).one()
                cs.session_closed = True


def _process_recordings(meet_service, drive_service, gmail_service) -> None:
    now = datetime.utcnow()
    ready_threshold = now - timedelta(minutes=settings.recording_check_delay_minutes)
    lookback_threshold = now - timedelta(hours=12)

    with get_session() as session:
        candidates = session.query(ClassSession).filter(
            ClassSession.recording_filed == False,  # noqa: E712
            ClassSession.scheduled_end <= ready_threshold,
            ClassSession.scheduled_end > lookback_threshold,
        ).all()
        candidate_ids = [cs.id for cs in candidates]

    for session_id in candidate_ids:
        attempts = _recording_retry_counts.get(session_id, 0)
        if attempts >= settings.recording_check_max_retries:
            continue

        try:
            found = try_file_recording_for_session(meet_service, drive_service, session_id)
        except Exception as exc:
            found = False
            logger.error("Unhandled error filing recording for session %s: %s", session_id, exc)

        if found:
            _recording_retry_counts.pop(session_id, None)
            continue

        attempts += 1
        _recording_retry_counts[session_id] = attempts
        if attempts >= settings.recording_check_max_retries:
            logger.error("Recording never appeared for class_session_id=%s after %d attempts — alerting.", session_id, attempts)
            send_alert(
                gmail_service,
                subject="[ALERT] Recording never appeared",
                body_text=(
                    f"class_session_id={session_id} finished, but no recording was found in Drive "
                    f"after {attempts} check(s). Please check Meet/Drive manually."
                ),
            )


def tick(calendar_service, meet_service, drive_service, gmail_service) -> None:
    logger.debug("Scheduler tick starting.")
    try:
        sync_recent_and_upcoming_sessions(calendar_service)
    except Exception as exc:
        logger.error("Calendar sync failed during tick: %s", exc)

    try:
        _process_session_close(meet_service)
    except Exception as exc:
        logger.error("Session close processing failed during tick: %s", exc)

    try:
        _process_recordings(meet_service, drive_service, gmail_service)
    except Exception as exc:
        logger.error("Recording processing failed during tick: %s", exc)

    logger.debug("Scheduler tick complete.")


def build_scheduler(calendar_service, meet_service, drive_service, gmail_service) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        tick,
        "interval",
        minutes=settings.scheduler_poll_interval_minutes,
        args=[calendar_service, meet_service, drive_service, gmail_service],
        id="main_tick",
        next_run_time=datetime.now(),
    )
    return scheduler
