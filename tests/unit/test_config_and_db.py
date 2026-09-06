import os
import pytest
from pathlib import Path
from media_sorter.config import Settings, ActionType, ConflictPolicy
from media_sorter.db import get_engine, init_db, get_db_session
from media_sorter.models import BatchRecord, Operation, FileRecord, QuarantineRecord


def test_settings_defaults():
    settings = Settings()
    assert settings.general.dry_run is True
    assert settings.general.confidence_threshold == 0.75
    assert settings.general.action == ActionType.MOVE
    assert settings.conflicts.policy == ConflictPolicy.RENAME_UNIQUE
    assert settings.conflicts.allow_overwrite is False
    assert "*.txt" in settings.filters.exclude_patterns

    from media_sorter.scanner import Scanner
    scanner = Scanner()
    assert "*.txt" in scanner.exclude_patterns
    assert not scanner._matches_filter("info.txt")
    assert not scanner._matches_filter("README.TXT")
    assert scanner._matches_filter("movie.mkv")


def test_load_yaml_config(tmp_path: Path):
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text("""
general:
  dry_run: false
  confidence_threshold: 0.85
storage:
  source_dirs:
    - "/test/source"
  destination_base: "/test/organized"
""", encoding="utf-8")

    settings = Settings.load_from_file(config_file)
    assert settings.general.dry_run is False
    assert settings.general.confidence_threshold == 0.85
    assert "/test/source" in settings.storage.source_dirs


def test_database_initialization(tmp_path: Path):
    db_file = tmp_path / "test.db"
    engine = init_db(db_path=db_file)
    assert db_file.exists()

    with get_db_session(engine) as session:
        batch = BatchRecord(id="test-uuid-1", dry_run=True, status="COMPLETED")
        session.add(batch)

    with get_db_session(engine) as session:
        queried = session.query(BatchRecord).filter_by(id="test-uuid-1").first()
        assert queried is not None
        assert queried.dry_run is True
        assert queried.status == "COMPLETED"


def test_session_factory_caching_and_cleanup(tmp_path: Path):
    from media_sorter.db import get_session_factory, _ENGINE_SESSION_FACTORIES
    db_file = tmp_path / "test_cache.db"
    engine = init_db(db_path=db_file)

    factory1 = get_session_factory(engine)
    factory2 = get_session_factory(engine)
    assert factory1 is factory2
    assert engine in _ENGINE_SESSION_FACTORIES

    with get_db_session(engine) as session:
        batch = BatchRecord(id="cached-1", dry_run=True, status="COMPLETED")
        session.add(batch)

    # Scoped session registry was cleared via remove()
    assert factory1.registry.has() is False
