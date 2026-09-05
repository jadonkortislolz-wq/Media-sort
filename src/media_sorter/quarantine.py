"""Quarantine and manual review management for Media Sorter.

Provides querying, manual override, reprocessing, and resolution tracking for files
that could not be safely or confidently organized automatically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy.orm import Session

from .models import QuarantineRecord, QuarantineStatus

logger = structlog.get_logger(__name__)


class QuarantineManager:
    """Manages files held in quarantine or review status."""

    def __init__(self, session: Session):
        self.session = session

    def list_pending(self) -> List[QuarantineRecord]:
        """Return all quarantine items waiting for human inspection."""
        return (
            self.session.query(QuarantineRecord)
            .filter_by(status=QuarantineStatus.PENDING.value)
            .order_by(QuarantineRecord.created_at.desc())
            .all()
        )

    def get_by_id(self, item_id: int) -> Optional[QuarantineRecord]:
        """Fetch quarantine record by ID."""
        return self.session.query(QuarantineRecord).filter_by(id=item_id).first()

    def resolve_item(
        self,
        item_id: int,
        resolved_category: str,
        target_path: Optional[Path | str] = None,
    ) -> bool:
        """Resolve a quarantined item by specifying human-approved category and target path."""
        rec = self.get_by_id(item_id)
        if not rec:
            return False

        rec.status = QuarantineStatus.RESOLVED.value
        rec.suggested_category = resolved_category
        rec.resolved_at = datetime.now(timezone.utc)
        if target_path:
            rec.resolved_path = str(target_path)

        self.session.commit()
        logger.info("Quarantine item resolved", item_id=item_id, category=resolved_category)
        return True

    def ignore_item(self, item_id: int) -> bool:
        """Mark quarantine item as ignored."""
        rec = self.get_by_id(item_id)
        if not rec:
            return False

        rec.status = QuarantineStatus.IGNORED.value
        rec.resolved_at = datetime.now(timezone.utc)
        self.session.commit()
        return True

    def get_statistics(self) -> Dict[str, int]:
        """Summarize quarantine records by status."""
        total = self.session.query(QuarantineRecord).count()
        pending = (
            self.session.query(QuarantineRecord)
            .filter_by(status=QuarantineStatus.PENDING.value)
            .count()
        )
        resolved = (
            self.session.query(QuarantineRecord)
            .filter_by(status=QuarantineStatus.RESOLVED.value)
            .count()
        )
        ignored = (
            self.session.query(QuarantineRecord)
            .filter_by(status=QuarantineStatus.IGNORED.value)
            .count()
        )

        return {
            "total": total,
            "pending": pending,
            "resolved": resolved,
            "ignored": ignored,
        }
