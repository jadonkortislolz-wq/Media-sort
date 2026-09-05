from pathlib import Path
import pytest
from media_sorter.db import get_db_session, init_db
from media_sorter.models import QuarantineRecord, QuarantineStatus
from media_sorter.quarantine import QuarantineManager


@pytest.fixture
def session(tmp_path: Path):
    db_file = tmp_path / "test.db"
    engine = init_db(db_path=db_file)
    with get_db_session(engine) as s:
        yield s


def test_quarantine_crud(session):
    qm = QuarantineManager(session)

    # Insert pending item
    item = QuarantineRecord(
        src="/incoming/ambiguous.avi",
        suggested_category="movie",
        confidence=0.55,
        reason="Missing release year and technical tags",
        status=QuarantineStatus.PENDING.value,
    )
    session.add(item)
    session.commit()

    pending = qm.list_pending()
    assert len(pending) == 1
    assert pending[0].src == "/incoming/ambiguous.avi"

    # Resolve item
    success = qm.resolve_item(pending[0].id, "tv", "/organized/TV/Show/ep.avi")
    assert success is True

    resolved = qm.get_by_id(pending[0].id)
    assert resolved.status == QuarantineStatus.RESOLVED.value
    assert resolved.suggested_category == "tv"
    assert resolved.resolved_path == "/organized/TV/Show/ep.avi"

    # Pending list should now be empty
    assert len(qm.list_pending()) == 0

    stats = qm.get_statistics()
    assert stats["total"] == 1
    assert stats["pending"] == 0
    assert stats["resolved"] == 1
