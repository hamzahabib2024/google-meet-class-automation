"""
check_status.py — run this to see exactly what state each batch and
class session is in. Run from the project folder with your .env active:

    python check_status.py
"""

from src.db import init_db, get_session, Batch, ClassSession

init_db()
with get_session() as s:
    print("=== ALL BATCHES ===")
    for b in s.query(Batch).all():
        print(
            f"{b.section_name!r} | meet_link={b.meet_link!r} | "
            f"meet_space_id={b.meet_space_id!r} | drive_folder_id={b.drive_folder_id!r}"
        )

    print()
    print("=== ALL CLASS SESSIONS ===")
    for cs in s.query(ClassSession).all():
        print(
            f"batch_id={cs.batch_id} | event={cs.calendar_event_id} | "
            f"end={cs.scheduled_end} | closed={cs.session_closed} | "
            f"recording_filed={cs.recording_filed}"
        )
