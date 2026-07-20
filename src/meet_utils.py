"""
meet_utils.py

Small helper module with the two Meet API actions this scoped-down project
actually needs:
  - resolve_space_id(): figure out (and cache) a batch's Meet space
    resource name from its permanent link, needed for every other Meet
    API call.
  - close_session(): end the active conference after class, so the room
    doesn't stay open.

NOTE: verify these exact call shapes against current Meet API v2 docs once
real credentials are available — the API surface has shifted before.
"""

import logging
import re
from typing import Optional

from src.db import get_session, Batch

logger = logging.getLogger(__name__)


def _extract_meeting_code(meet_link: str) -> Optional[str]:
    match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", meet_link)
    return match.group(1) if match else None


def resolve_space_id(meet_service, batch: Batch) -> Optional[str]:
    """Resolves and caches the Meet space resource name for a batch."""
    if batch.meet_space_id:
        return batch.meet_space_id

    meeting_code = _extract_meeting_code(batch.meet_link)
    if not meeting_code:
        logger.warning("Could not parse a meeting code out of link '%s' for batch '%s'.", batch.meet_link, batch.section_name)
        return None

    try:
        space = meet_service.spaces().get(name=f"spaces/{meeting_code}").execute()
        space_id = space.get("name")
    except Exception as exc:
        logger.error("Failed to resolve Meet space for batch '%s': %s", batch.section_name, exc)
        return None

    if space_id:
        with get_session() as session:
            db_batch = session.query(Batch).filter_by(id=batch.id).one()
            db_batch.meet_space_id = space_id
        logger.info("Resolved and cached space id '%s' for batch '%s'", space_id, batch.section_name)

    return space_id


def close_session(meet_service, space_id: str, batch_name: str) -> bool:
    """Ends the active conference for a space. Returns True on success."""
    try:
        meet_service.spaces().endActiveConference(name=space_id).execute()
        logger.info("Closed Meet session for batch '%s'.", batch_name)
        return True
    except Exception as exc:
        logger.error("Failed to close Meet session for batch '%s': %s", batch_name, exc)
        return False
