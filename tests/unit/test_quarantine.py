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


def test_quarantine_undo(session, tmp_path: Path):
    qm = QuarantineManager(session)

    # 1. Test unflagging a pending item
    src_file = tmp_path / "pending_sample.mkv"
    src_file.write_text("dummy")

    item1 = QuarantineRecord(
        src=str(src_file),
        suggested_category="movie",
        confidence=0.50,
        reason="Low confidence",
        status=QuarantineStatus.PENDING.value,
    )
    session.add(item1)
    session.commit()

    assert len(qm.list_pending()) == 1
    # Undo pending item should delete/unflag it
    success = qm.undo_item(item1.id)
    assert success is True
    assert len(qm.list_pending()) == 0
    assert qm.get_by_id(item1.id) is None

    # 2. Test undoing a resolved item (moves file back to src)
    if src_file.exists():
        src_file.unlink()
    dst_file = tmp_path / "organized" / "Movie (2020)" / "Movie (2020).mkv"
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    dst_file.write_text("movie data")

    item2 = QuarantineRecord(
        src=str(src_file),
        suggested_category="movie",
        confidence=0.60,
        reason="Ambiguous",
        status=QuarantineStatus.RESOLVED.value,
        resolved_path=str(dst_file),
    )
    session.add(item2)
    session.commit()

    assert len(qm.list_resolved()) == 1
    assert dst_file.exists()
    assert not src_file.exists()

    success2 = qm.undo_item(item2.id)
    assert success2 is True

    # File should be moved back to src
    assert src_file.exists()
    assert src_file.read_text() == "movie data"
    assert not dst_file.exists()

    # Record should now be back to PENDING with resolved fields reset
    rec2 = qm.get_by_id(item2.id)
    assert rec2.status == QuarantineStatus.PENDING.value
    assert rec2.resolved_path is None
    assert len(qm.list_pending()) == 1
    assert len(qm.list_resolved()) == 0

