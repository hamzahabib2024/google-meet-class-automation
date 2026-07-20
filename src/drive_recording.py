"""
drive_recording.py

Finds the Meet recording for a finished class and files it into a
batch-specific Drive folder:

    /{DRIVE_RECORDINGS_ROOT_FOLDER}/{Batch Name}/{YYYY-MM-DD} - {Subject}.mp4

Single-shot check — call try_file_recording_for_session() repeatedly (the
scheduler does this every tick) until it returns True or retries run out,
since recordings take time to process after class ends.

NOTE: verify exact Meet API v2 resource names for conferenceRecords/
recordings against current docs once real credentials are available.
"""

import logging
from typing import Optional

from src.config import settings
from src.db import get_session, ClassSession, Batch, RecordingLog
from src.meet_utils import resolve_space_id

logger = logging.getLogger(__name__)

DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"


def _find_conference_record(meet_service, space_id: str, session_start) -> Optional[str]:
    try:
        response = meet_service.conferenceRecords().list(filter=f'space.name="{space_id}"').execute()
    except Exception as exc:
        logger.error("Failed to list conference records for space %s: %s", space_id, exc)
        return None

    records = response.get("conferenceRecords", [])
    for record in records:
        record_start = record.get("startTime")
        if record_start and session_start.isoformat()[:10] in record_start:
            return record.get("name")
    if records:
        return records[0].get("name")
    return None


def _find_recording_file_id(meet_service, conference_record_name: str) -> Optional[str]:
    try:
        response = meet_service.conferenceRecords().recordings().list(parent=conference_record_name).execute()
    except Exception as exc:
        logger.error("Failed to list recordings for %s: %s", conference_record_name, exc)
        return None

    recordings = response.get("recordings", [])
    if not recordings:
        return None
    return recordings[0].get("driveDestination", {}).get("file")


def _find_or_create_folder(drive_service, name: str, parent_id: Optional[str] = None) -> str:
    query = f"name = '{name}' and mimeType = '{DRIVE_FOLDER_MIME}' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    existing = results.get("files", [])
    if existing:
        return existing[0]["id"]

    metadata = {"name": name, "mimeType": DRIVE_FOLDER_MIME}
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = drive_service.files().create(body=metadata, fields="id").execute()
    logger.info("Created Drive folder '%s' (parent=%s)", name, parent_id)
    return folder["id"]


def _get_or_create_batch_folder(drive_service, batch: Batch) -> str:
    if batch.drive_folder_id:
        return batch.drive_folder_id

    root_folder_id = _find_or_create_folder(drive_service, settings.drive_recordings_root_folder)
    batch_folder_id = _find_or_create_folder(drive_service, batch.section_name, parent_id=root_folder_id)

    with get_session() as session:
        db_batch = session.query(Batch).filter_by(id=batch.id).one()
        db_batch.drive_folder_id = batch_folder_id

    return batch_folder_id


def _move_and_rename_file(drive_service, file_id: str, new_parent_id: str, new_name: str) -> str:
    file_metadata = drive_service.files().get(fileId=file_id, fields="parents").execute()
    previous_parents = ",".join(file_metadata.get("parents", []))

    updated = drive_service.files().update(
        fileId=file_id,
        addParents=new_parent_id,
        removeParents=previous_parents,
        body={"name": new_name},
        fields="id, webViewLink",
    ).execute()
    return updated.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")


def try_file_recording_for_session(meet_service, drive_service, class_session_id: int) -> bool:
    """Single-shot attempt to find and file the recording. True = done (or already done)."""
    with get_session() as session:
        class_session = session.query(ClassSession).filter_by(id=class_session_id).one_or_none()
        if class_session is None:
            logger.error("try_file_recording_for_session called with unknown id=%s", class_session_id)
            return False
        if class_session.recording_filed:
            return True

        batch = session.query(Batch).filter_by(id=class_session.batch_id).one()
        session_start = class_session.scheduled_start
        batch_id = batch.id
        batch_section_name = batch.section_name
        batch_subject = batch.subject

    # Resolve space id on the fly if it wasn't cached yet.
    with get_session() as session:
        batch = session.query(Batch).filter_by(id=batch_id).one()
        space_id = resolve_space_id(meet_service, batch)

    if not space_id:
        return False

    conference_record = _find_conference_record(meet_service, space_id, session_start)
    if not conference_record:
        logger.debug("No conference record yet for batch '%s' session %s", batch_section_name, session_start)
        return False

    file_id = _find_recording_file_id(meet_service, conference_record)
    if not file_id:
        logger.debug("Recording not yet available for batch '%s' session %s", batch_section_name, session_start)
        return False

    with get_session() as session:
        batch = session.query(Batch).filter_by(id=batch_id).one()
        batch_folder_id = _get_or_create_batch_folder(drive_service, batch)

    new_name = f"{session_start.strftime('%Y-%m-%d')} - {batch_subject}.mp4"
    drive_link = _move_and_rename_file(drive_service, file_id, batch_folder_id, new_name)

    with get_session() as session:
        class_session = session.query(ClassSession).filter_by(id=class_session_id).one()
        class_session.recording_filed = True
        class_session.recording_drive_link = drive_link
        session.add(RecordingLog(class_session_id=class_session_id, drive_file_id=file_id, drive_link=drive_link))

    logger.info("Filed recording for batch '%s' session %s -> %s", batch_section_name, session_start, drive_link)
    return True
