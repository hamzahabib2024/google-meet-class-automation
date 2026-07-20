"""
db.py

Data model for the smaller-scope project: just enough to know which batch
a class belongs to, track each class occurrence, and log filed recordings.

Tables:
- Batch        — one row per class section: name, permanent Meet link,
                  cached Meet space id, cached Drive folder id.
- ClassSession — one row per actual scheduled class, tracks whether it's
                  been closed and whether its recording has been filed.
- RecordingLog — one row per recording successfully filed into Drive.
"""

import logging
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from src.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()


class Batch(Base):
    __tablename__ = "batches"

    id = Column(Integer, primary_key=True)
    section_name = Column(String, nullable=False, unique=True)
    subject = Column(String, nullable=False)
    meet_link = Column(String, nullable=False)
    meet_space_id = Column(String, nullable=True)   # cached, e.g. "spaces/abc123"
    drive_folder_id = Column(String, nullable=True)  # cached Drive folder for this batch
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("ClassSession", back_populates="batch", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Batch {self.section_name!r}>"


class ClassSession(Base):
    __tablename__ = "class_sessions"

    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=False)
    calendar_event_id = Column(String, nullable=False, unique=True)
    scheduled_start = Column(DateTime, nullable=False)
    scheduled_end = Column(DateTime, nullable=False)

    session_closed = Column(Boolean, default=False)
    recording_filed = Column(Boolean, default=False)
    recording_drive_link = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    batch = relationship("Batch", back_populates="sessions")

    def __repr__(self):
        return f"<ClassSession batch_id={self.batch_id} start={self.scheduled_start}>"


class RecordingLog(Base):
    __tablename__ = "recording_logs"

    id = Column(Integer, primary_key=True)
    class_session_id = Column(Integer, ForeignKey("class_sessions.id"), nullable=False, unique=True)
    drive_file_id = Column(String, nullable=False)
    drive_link = Column(String, nullable=False)
    filed_at = Column(DateTime, default=datetime.utcnow)


_engine = None
_SessionLocal = None


def init_db() -> None:
    global _engine, _SessionLocal
    import os
    db_dir = os.path.dirname(settings.database_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    _engine = create_engine(f"sqlite:///{settings.database_path}", echo=False)
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine)
    logger.info("Database initialized at %s", settings.database_path)


@contextmanager
def get_session():
    if _SessionLocal is None:
        raise RuntimeError("init_db() must be called before get_session().")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
