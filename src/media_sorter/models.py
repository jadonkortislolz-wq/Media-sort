"""SQLAlchemy database models for Media Sorter.

Provides data structures for file tracking, operation journaling, quarantine,
batch execution, and configuration auditing.
"""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class OperationStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    SKIPPED = "SKIPPED"


class QuarantineStatus(str, Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


class BatchRecord(Base):
    """Tracks an execution batch (one invocation of media-sorter run or dry-run)."""

    __tablename__ = "batches"

    id = Column(String(36), primary_key=True)  # UUIDv4
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    dry_run = Column(Boolean, default=False, nullable=False)
    status = Column(String(32), default="IN_PROGRESS", nullable=False)  # IN_PROGRESS, COMPLETED, FAILED, ROLLED_BACK
    total_files = Column(Integer, default=0, nullable=False)
    moved_files = Column(Integer, default=0, nullable=False)
    skipped_files = Column(Integer, default=0, nullable=False)
    failed_files = Column(Integer, default=0, nullable=False)
    quarantined_files = Column(Integer, default=0, nullable=False)

    operations = relationship("Operation", back_populates="batch", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_batches_created_at", "created_at"),
    )


class FileRecord(Base):
    """Tracks known files to avoid redundant probing and detect changes."""

    __tablename__ = "files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String(1024), unique=True, nullable=False)
    size = Column(Integer, nullable=False)
    mtime = Column(Float, nullable=False)
    content_hash = Column(String(64), nullable=True)
    status = Column(String(32), default="scanned", nullable=False)  # scanned, organized, quarantined, skipped, error
    category = Column(String(32), nullable=True)
    confidence = Column(Float, nullable=True)
    first_seen = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_processed = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_files_path", "path"),
        Index("ix_files_status", "status"),
    )


class Operation(Base):
    """Operation journal entry for atomic moves, copies, or links."""

    __tablename__ = "operations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(36), ForeignKey("batches.id"), nullable=False)
    src = Column(String(1024), nullable=False)
    dst = Column(String(1024), nullable=False)
    action = Column(String(32), nullable=False)  # move, copy, link, hardlink
    status = Column(String(32), default=OperationStatus.PLANNED.value, nullable=False)
    category = Column(String(32), nullable=True)
    confidence = Column(Float, nullable=True)
    src_hash = Column(String(64), nullable=True)
    dst_hash = Column(String(64), nullable=True)
    backup_path = Column(String(1024), nullable=True)
    details = Column(JSON, nullable=True)  # reasoning, sidecars, format info
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    batch = relationship("BatchRecord", back_populates="operations")

    __table_args__ = (
        Index("ix_operations_batch_id", "batch_id"),
        Index("ix_operations_status", "status"),
        Index("ix_operations_src", "src"),
        Index("ix_operations_dst", "dst"),
    )


class QuarantineRecord(Base):
    """Stores files that failed confidence threshold or require manual user review."""

    __tablename__ = "quarantine"

    id = Column(Integer, primary_key=True, autoincrement=True)
    src = Column(String(1024), unique=True, nullable=False)
    suggested_category = Column(String(32), nullable=True)
    confidence = Column(Float, nullable=True)
    reason = Column(String(256), nullable=False)
    signals = Column(JSON, nullable=True)  # Diagnostic details of why it was flagged
    status = Column(String(32), default=QuarantineStatus.PENDING.value, nullable=False)
    resolved_path = Column(String(1024), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_quarantine_status", "status"),
        Index("ix_quarantine_src", "src"),
    )


class ConfigAudit(Base):
    """Tracks configuration states for reproducibility and auditing."""

    __tablename__ = "config_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    loaded_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    config_json = Column(JSON, nullable=False)

    __table_args__ = (
        Index("ix_config_loaded", "loaded_at"),
    )


class LibraryItem(Base):
    """Tracks known shows and movies in the user's library for automated routing and cataloging."""

    __tablename__ = "library_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    category = Column(String(32), nullable=False)  # "tv" or "movie"
    year = Column(Integer, nullable=True)
    destination_folder = Column(String(1024), nullable=False)
    poster_url = Column(String(1024), nullable=True)
    item_count = Column(Integer, default=0, nullable=False)
    seasons_count = Column(Integer, default=0, nullable=False)
    first_detected = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_updated = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    extra_info = Column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("title", "category", name="uq_library_title_category"),
        Index("ix_library_category", "category"),
        Index("ix_library_title", "title"),
    )

