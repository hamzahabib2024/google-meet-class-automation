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
from datetime import datetime, timezone
from typing import Optional

from src.config import settings
from src.db import get_session, ClassSession, Batch, RecordingLog
from src.meet_utils import resolve_space_id

logger = logging.getLogger(__name__)

DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"


def _escape_drive_query_value(value: str) -> str:
    """Escapes a value for safe interpolation into a Drive `q` query string.
    Without this, a folder/batch name containing a single quote (e.g.
    "O'Brien's Section") breaks the query syntax and the API call fails."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find_conference_record(meet_service, space_id: str, session_start) -> Optional[str]:
    try:
        records = []
        page_token = None
        while True:
            request = meet_service.conferenceRecords().list(
                filter=f'space.name = "{space_id}"',
                pageSize=100,
                pageToken=page_token,
            )
            response = request.execute()
            records.extend(response.get("conferenceRecords", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        logger.error("Failed to list conference records for space %s: %s", space_id, exc)
        return None

    if not records:
        logger.info("No conference record found yet for Meet space %s", space_id)
        return None

    # Prefer the conference that belongs to this calendar occurrence. A
    # permanent Meet link can have many conference records over time.
    closest_record = None
    closest_delta = None
    for record in records:
        record_start = record.get("startTime")
        if not record_start or not record.get("name"):
            continue
        try:
            start = datetime.fromisoformat(record_start.replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            expected = session_start.replace(tzinfo=timezone.utc)
            delta = abs((start - expected).total_seconds())
            if closest_delta is None or delta < closest_delta:
                closest_record = record.get("name")
                closest_delta = delta
        except ValueError:
            continue

    # Calendar and Meet timestamps can differ slightly. Do not associate a
    # recording from a different class unless it started within two hours.
    if closest_record is not None and closest_delta is not None and closest_delta <= 7200:
        return closest_record

    logger.warning("Conference records exist for %s, but none matched session start %s", space_id, session_start)
    return None


def _find_recording_file_id(meet_service, conference_record_name: str) -> Optional[str]:
    try:
        recordings = []
        page_token = None
        while True:
            request = meet_service.conferenceRecords().recordings().list(
                parent=conference_record_name,
                pageSize=100,
                pageToken=page_token,
            )
            response = request.execute()
            recordings.extend(response.get("recordings", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        logger.error("Failed to list recordings for %s: %s", conference_record_name, exc)
        return None

    for recording in recordings:
        # Per the Meet API docs, driveDestination.file is only reliably
        # populated once the recording session has reached FILE_GENERATED —
        # earlier states (STARTED, ENDED) mean the MP4 isn't ready yet.
        if recording.get("state") == "FILE_GENERATED":
            file_id = recording.get("driveDestination", {}).get("file")
            if file_id:
                return file_id
    if recordings:
        logger.info("Recording exists for %s but is still processing (states=%s)", conference_record_name, [r.get("state") for r in recordings])
    return None


def _find_drive_recording_file_id(drive_service, session_start, batch_name: str, subject: str) -> Optional[str]:
    """Fallback for recordings visible in Drive but not returned by Meet API.

    This can happen when the recording was created by a different organizer
    account, or when Meet has already generated the Drive file but its
    conference-record resource is unavailable to the OAuth account.
    """
    try:
        start = session_start.replace(tzinfo=timezone.utc)
        earliest = start.timestamp() - 2 * 60 * 60
        earliest_iso = datetime.fromtimestamp(earliest, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        queries = [
            f"name contains '{_escape_drive_query_value(batch_name)}'",
            f"name contains '{_escape_drive_query_value(subject)}'",
        ]
        candidates = {}
        for name_query in queries:
            response = drive_service.files().list(
                q=(
                    f"trashed = false and mimeType = 'video/mp4' and "
                    f"createdTime >= '{earliest_iso}' and {name_query}"
                ),
                orderBy="createdTime desc",
                pageSize=100,
                fields="files(id,name,mimeType,createdTime,webViewLink)",
            ).execute()
            for file in response.get("files", []):
                candidates[file["id"]] = file

        if len(candidates) == 1:
            file = next(iter(candidates.values()))
            logger.info("Found recording directly in Drive as fallback: %s (%s)", file["name"], file["id"])
            return file["id"]
        if candidates:
            logger.warning(
                "Found %d possible Drive recordings for batch '%s'; not moving automatically: %s",
                len(candidates), batch_name, [file["name"] for file in candidates.values()],
            )
    except Exception as exc:
        logger.error("Drive fallback search failed for batch '%s': %s", batch_name, exc)
    return None


def _find_or_create_folder(drive_service, name: str, parent_id: Optional[str] = None) -> str:
    escaped_name = _escape_drive_query_value(name)
    query = f"name = '{escaped_name}' and mimeType = '{DRIVE_FOLDER_MIME}' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    existing = results.get("files", [])
    if existing:
        return existing[0]["id"]

    # Use the raw (unescaped) name here — escaping is only needed inside the
    # `q` query string above, not in the resource body sent to files.create.
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
    file_metadata = drive_service.files().get(fileId=file_id, fields="parents, name").execute()
    previous_parents = ",".join(file_metadata.get("parents", []))

    update_args = dict(
        fileId=file_id,
        addParents=new_parent_id,
        body={"name": new_name},
        fields="id, webViewLink",
    )
    if previous_parents:
        update_args["removeParents"] = previous_parents
    updated = drive_service.files().update(**update_args).execute()
    return updated.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")


def _unique_recording_name(drive_service, folder_id: str, base_name: str, file_id: str) -> str:
    """Prevent a same-name Drive file from being renamed over semantically."""
    stem, extension = base_name.rsplit(".", 1)
    candidate = base_name
    suffix = 2
    while True:
        escaped = _escape_drive_query_value(candidate)
        result = drive_service.files().list(
            q=(
                f"'{folder_id}' in parents and name = '{escaped}' and "
                "trashed = false"
            ),
            fields="files(id)",
            pageSize=10,
        ).execute()
        conflicts = [item for item in result.get("files", []) if item.get("id") != file_id]
        if not conflicts:
            return candidate
        candidate = f"{stem} ({suffix}).{extension}"
        suffix += 1


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
    file_id = _find_recording_file_id(meet_service, conference_record) if conference_record else None
    if not file_id:
        file_id = _find_drive_recording_file_id(
            drive_service, session_start, batch_section_name, batch_subject
        )
    if not file_id:
        logger.debug("Recording not yet available for batch '%s' session %s", batch_section_name, session_start)
        return False

    with get_session() as session:
        batch = session.query(Batch).filter_by(id=batch_id).one()
        batch_folder_id = _get_or_create_batch_folder(drive_service, batch)

    base_name = f"{session_start.strftime('%Y-%m-%d %H-%M')} - {batch_subject}.mp4"
    new_name = _unique_recording_name(drive_service, batch_folder_id, base_name, file_id)
    drive_link = _move_and_rename_file(drive_service, file_id, batch_folder_id, new_name)

    with get_session() as session:
        class_session = session.query(ClassSession).filter_by(id=class_session_id).one()
        class_session.recording_filed = True
        class_session.recording_drive_link = drive_link
        session.add(RecordingLog(class_session_id=class_session_id, drive_file_id=file_id, drive_link=drive_link))

    logger.info("Filed recording for batch '%s' session %s -> %s", batch_section_name, session_start, drive_link)
    return True
