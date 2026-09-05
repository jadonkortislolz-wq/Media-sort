from pathlib import Path
import pytest
from media_sorter.config import ActionType, ConflictPolicy, Settings
from media_sorter.db import get_db_session, init_db
from media_sorter.executor import MediaExecutor, PlannedOperation
from media_sorter.models import BatchRecord, Operation, OperationStatus


@pytest.fixture
def temp_env(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine = init_db(db_path=db_path)
    src_dir = tmp_path / "incoming"
    src_dir.mkdir()
    dst_dir = tmp_path / "organized"
    dst_dir.mkdir()

    settings = Settings()
    settings.database.path = str(db_path)
    settings.storage.destination_base = str(dst_dir)
    settings.storage.source_dirs = [str(src_dir)]

    return settings, engine, src_dir, dst_dir


def test_dry_run_leaves_filesystem_untouched(temp_env):
    settings, engine, src_dir, dst_dir = temp_env
    test_file = src_dir / "sample_movie.mkv"
    test_file.write_text("dummy content")

    target_dst = dst_dir / "Movies/sample_movie.mkv"

    with get_db_session(engine) as session:
        executor = MediaExecutor(settings, session)
        plan = [
            PlannedOperation(
                src=test_file,
                dst=target_dst,
                action=ActionType.MOVE,
                category="movie",
                confidence=0.95,
            )
        ]
        report = executor.execute_batch(plan, dry_run=True)

    assert report.dry_run is True
    assert report.moved_files == 1
    # File must still exist at src and not at dst
    assert test_file.exists()
    assert not target_dst.exists()


def test_live_atomic_move_and_rollback(temp_env):
    settings, engine, src_dir, dst_dir = temp_env
    settings.general.dry_run = False
    test_file = src_dir / "song.flac"
    test_file.write_text("flac audio bytes")

    target_dst = dst_dir / "Music/Artist/Album/01 - song.flac"

    with get_db_session(engine) as session:
        executor = MediaExecutor(settings, session)
        plan = [
            PlannedOperation(
                src=test_file,
                dst=target_dst,
                action=ActionType.MOVE,
                category="music",
                confidence=0.95,
            )
        ]
        report = executor.execute_batch(plan, dry_run=False)

    assert report.moved_files == 1
    assert not test_file.exists()
    assert target_dst.exists()
    assert target_dst.read_text() == "flac audio bytes"

    # Now execute rollback
    with get_db_session(engine) as session:
        executor = MediaExecutor(settings, session)
        reverted = executor.rollback_batch(report.batch_id)

    assert reverted == 1
    assert test_file.exists()
    assert not target_dst.exists()
    assert test_file.read_text() == "flac audio bytes"


def test_conflict_rename_unique(temp_env):
    settings, engine, src_dir, dst_dir = temp_env
    settings.general.dry_run = False
    settings.conflicts.policy = ConflictPolicy.RENAME_UNIQUE

    # Pre-create existing file at destination
    target_dst = dst_dir / "Movies/Avatar (2009)/Avatar (2009).mkv"
    target_dst.parent.mkdir(parents=True, exist_ok=True)
    target_dst.write_text("original 1080p copy")

    # New incoming file
    incoming = src_dir / "Avatar.2009.2160p.mkv"
    incoming.write_text("new 4k copy")

    with get_db_session(engine) as session:
        executor = MediaExecutor(settings, session)
        plan = [
            PlannedOperation(
                src=incoming,
                dst=target_dst,
                action=ActionType.MOVE,
                category="movie",
                confidence=0.95,
            )
        ]
        report = executor.execute_batch(plan, dry_run=False)

    assert report.moved_files == 1
    assert target_dst.exists()
    assert target_dst.read_text() == "original 1080p copy"

    # New file should have been renamed uniquely: Avatar (2009) (1).mkv
    unique_dst = dst_dir / "Movies/Avatar (2009)/Avatar (2009) (1).mkv"
    assert unique_dst.exists()
    assert unique_dst.read_text() == "new 4k copy"


def test_conflict_replace_with_backup_and_rollback(temp_env):
    settings, engine, src_dir, dst_dir = temp_env
    settings.general.dry_run = False
    settings.conflicts.policy = ConflictPolicy.REPLACE_IF_HIGHER_QUALITY
    backup_dir = src_dir.parent / ".backup"
    settings.conflicts.backup_dir = str(backup_dir)

    target_dst = dst_dir / "Movies/Test.mkv"
    target_dst.parent.mkdir(parents=True, exist_ok=True)
    target_dst.write_text("old version")

    incoming = src_dir / "Test.mkv"
    incoming.write_text("upgraded high quality version")

    with get_db_session(engine) as session:
        executor = MediaExecutor(settings, session)
        plan = [
            PlannedOperation(
                src=incoming,
                dst=target_dst,
                action=ActionType.MOVE,
                category="movie",
                confidence=0.95,
            )
        ]
        report = executor.execute_batch(plan, dry_run=False)

    assert target_dst.read_text() == "upgraded high quality version"

    # Rollback should restore the old version from backup!
    with get_db_session(engine) as session:
        executor = MediaExecutor(settings, session)
        reverted = executor.rollback_batch(report.batch_id)

    assert reverted == 1
    assert target_dst.read_text() == "old version"
    assert incoming.read_text() == "upgraded high quality version"


def test_process_locking(tmp_path: Path):
    from media_sorter.executor import acquire_process_lock, ProcessLockError
    lock_file = tmp_path / "test.lock"

    with acquire_process_lock(lock_file):
        # Trying to acquire same lock file concurrently must fail with ProcessLockError
        with pytest.raises(ProcessLockError):
            with acquire_process_lock(lock_file):
                pass

    # After exiting the lock block, it should be cleanly re-acquirable
    with acquire_process_lock(lock_file):
        pass


def test_cleanup_deletes_txt_files_and_removes_dirs(temp_env):
    settings, engine, src_dir, dst_dir = temp_env
    settings.general.dry_run = False
    settings.general.cleanup_empty_dirs = True

    # Setup source subdirectory with a movie, a .txt file, and a companion .txt file
    sub_dir = src_dir / "Movie.Release.2023"
    sub_dir.mkdir(parents=True, exist_ok=True)

    movie_file = sub_dir / "movie.mkv"
    movie_file.write_text("dummy video")
    companion_txt = sub_dir / "movie.txt"
    companion_txt.write_text("companion text")
    readme_txt = sub_dir / "README.txt"
    readme_txt.write_text("torrent info")
    root_txt = src_dir / "root_note.txt"
    root_txt.write_text("root text file")

    target_dst = dst_dir / "Movies/Movie (2023)/movie.mkv"

    with get_db_session(engine) as session:
        executor = MediaExecutor(settings, session)
        plan = [
            PlannedOperation(
                src=movie_file,
                dst=target_dst,
                action=ActionType.MOVE,
                category="movie",
                confidence=0.95,
            )
        ]
        report = executor.execute_batch(plan, dry_run=False)

    assert report.moved_files == 1
    assert target_dst.exists()

    # Verify movie is gone from src
    assert not movie_file.exists()
    # Verify .txt files were deleted during cleanup
    assert not companion_txt.exists()
    assert not readme_txt.exists()
    assert not root_txt.exists()
    # Verify the empty subdirectory was cleaned up (rmdir'd)
    assert not sub_dir.exists()
    # Verify source root itself was NOT removed
    assert src_dir.exists()


def test_rollback_all_batches(temp_env):
    settings, engine, src_dir, dst_dir = temp_env
    settings.general.dry_run = False

    file1 = src_dir / "sample1.mkv"
    file1.write_text("file 1")
    file2 = src_dir / "sample2.mkv"
    file2.write_text("file 2")

    dst1 = dst_dir / "Movies/Movie 1/sample1.mkv"
    dst2 = dst_dir / "Movies/Movie 2/sample2.mkv"

    with get_db_session(engine) as session:
        executor = MediaExecutor(settings, session)
        executor.execute_batch(
            [PlannedOperation(src=file1, dst=dst1, action=ActionType.MOVE, category="movie", confidence=0.9)],
            dry_run=False
        )
        executor.execute_batch(
            [PlannedOperation(src=file2, dst=dst2, action=ActionType.MOVE, category="movie", confidence=0.9)],
            dry_run=False
        )

    assert not file1.exists()
    assert not file2.exists()
    assert dst1.exists()
    assert dst2.exists()

    with get_db_session(engine) as session:
        executor = MediaExecutor(settings, session)
        reverted = executor.rollback_all()

    assert reverted == 2
    assert file1.exists()
    assert file2.exists()
    assert not dst1.exists()
    assert not dst2.exists()



