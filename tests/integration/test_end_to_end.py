import os
import time
from pathlib import Path
import pytest
from media_sorter.config import Settings
from media_sorter.db import get_db_session, init_db
from media_sorter.models import BatchRecord, Operation, QuarantineRecord
from media_sorter.sorter import MediaSorterApp


@pytest.fixture
def library_environment(tmp_path: Path):
    incoming = tmp_path / "incoming"
    organized = tmp_path / "organized"
    db_file = tmp_path / "media_sorter.db"
    incoming.mkdir()
    organized.mkdir()

    settings = Settings()
    settings.storage.source_dirs = [str(incoming)]
    settings.storage.destination_base = str(organized)
    settings.storage.destination_dirs.movies = "Movies"
    settings.storage.destination_dirs.tv = "TV Shows"
    settings.database.path = str(db_file)
    settings.general.min_file_age_seconds = 0  # Process immediately in test

    engine = init_db(db_path=db_file)
    return settings, engine, incoming, organized


def test_end_to_end_pipeline(library_environment):
    settings, engine, incoming, organized = library_environment

    # 1. Populate mock media files in incoming directory
    movie_file = incoming / "The.Dark.Knight.2008.1080p.BluRay.x264.mkv"
    movie_file.write_bytes(b"\x1aE\xdf\xa3" + b"\x00" * 200)  # EBML header

    sub_file = incoming / "The.Dark.Knight.2008.1080p.BluRay.x264.en.srt"
    sub_file.write_text("1\n00:00:01,000 --> 00:00:03,000\nBatman begins.\n")

    tv_file = incoming / "The.Wire.S01E01.Target.720p.mkv"
    tv_file.write_bytes(b"\x1aE\xdf\xa3" + b"\x00" * 200)

    photo_file = incoming / "IMG_20250620_153022.jpg"
    photo_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # JPEG header

    junk_file = incoming / "unrecognized_sample.xyz"
    junk_file.write_bytes(b"\x00\x01\x02\x03\x04")

    sorter = MediaSorterApp(settings, engine)

    # 2. First Run: Dry-Run
    dry_report = sorter.run(dry_run=True)
    assert dry_report.dry_run is True
    assert dry_report.total_files >= 4
    # Ensure source files were not modified
    assert movie_file.exists()
    assert sub_file.exists()
    assert tv_file.exists()
    assert photo_file.exists()
    assert junk_file.exists()

    # 3. Second Run: Live Organization
    live_report = sorter.run(dry_run=False)
    assert live_report.dry_run is False
    assert live_report.moved_files >= 3

    # Verify Movie and matched subtitle sidecar
    movie_dest_dir = organized / "Movies/The Dark Knight (2008)"
    assert movie_dest_dir.exists()
    dest_movie = list(movie_dest_dir.glob("*.mkv"))[0]
    assert "The Dark Knight" in dest_movie.name
    # Subtitle should be alongside movie with .en.srt
    dest_sub = list(movie_dest_dir.glob("*.srt"))[0]
    assert dest_sub.name.endswith(".en.srt")

    # Verify TV show organization
    tv_season_dir = organized / "TV Shows/The Wire/Season 01"
    assert tv_season_dir.exists()
    dest_tv = list(tv_season_dir.glob("*.mkv"))[0]
    assert "S01E01" in dest_tv.name

    # Verify Photo organization
    photo_dest_dir = organized / "Photos/2025/2025-06"
    assert photo_dest_dir.exists()

    # Verify Quarantine of unknown/low confidence file (flagged in place, not moved)
    assert junk_file.exists()
    from media_sorter.quarantine import QuarantineManager
    with get_db_session(engine) as s:
        qm = QuarantineManager(s)
        pending = qm.list_pending()
        assert any("unrecognized_sample.xyz" in q.src for q in pending)

    # 4. Third Step: Rollback
    reverted = sorter.rollback(live_report.batch_id)
    assert reverted >= 3

    # Verify files restored to incoming!
    assert movie_file.exists()
    assert sub_file.exists()
    assert tv_file.exists()
