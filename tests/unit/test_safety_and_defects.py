import os
from pathlib import Path
import socket
import pytest
from fastapi.testclient import TestClient
from media_sorter.config import Settings
from media_sorter.db import get_db_session, init_db
from media_sorter.library import record_detected_item
from media_sorter.models import LibraryItem
from media_sorter.server import create_app


@pytest.fixture
def isolated_web_env(tmp_path: Path):
    """Isolated environment with temporary directories and SQLite database."""
    downloads = tmp_path / "downloads"
    movies = tmp_path / "movies"
    shows = tmp_path / "shows"
    db_file = tmp_path / "test.db"
    downloads.mkdir()
    movies.mkdir()
    shows.mkdir()

    settings = Settings()
    settings.storage.source_dirs = [str(downloads)]
    settings.storage.destination_dirs.movies = str(movies)
    settings.storage.destination_dirs.tv = str(shows)
    settings.database.path = str(db_file)
    settings.general.dry_run = False
    settings.general.min_file_age_seconds = 0

    engine = init_db(db_path=db_file)
    test_env_file = tmp_path / ".env"
    app = create_app(settings, engine, env_path=test_env_file)
    client = TestClient(app)

    return client, settings, engine, downloads, movies, shows, test_env_file


# -----------------------------------------------------------------------------
# Test 1: Production Filesystem Safety Trap
# -----------------------------------------------------------------------------
def test_protect_production_filesystem_triggers_on_write(tmp_path: Path):
    """Verify protect_production_filesystem trap triggers RuntimeError on attempted
    write or delete in /md0/jdownloads/illegal.txt, /md0/movies1, /md0/tv1.
    """
    illegal_download = Path("/md0/jdownloads/illegal.txt")
    with pytest.raises(RuntimeError, match="FILESYSTEM SAFETY TRAP"):
        illegal_download.write_text("dangerous write")

    with pytest.raises(RuntimeError, match="FILESYSTEM SAFETY TRAP"):
        illegal_download.write_bytes(b"dangerous bytes")

    with pytest.raises(RuntimeError, match="FILESYSTEM SAFETY TRAP"):
        illegal_download.unlink()

    with pytest.raises(RuntimeError, match="FILESYSTEM SAFETY TRAP"):
        os.remove("/md0/jdownloads/illegal.txt")

    with pytest.raises(RuntimeError, match="FILESYSTEM SAFETY TRAP"):
        open("/md0/jdownloads/illegal.txt", "w")

    # Verify protection for /md0/movies1 and /md0/tv1
    with pytest.raises(RuntimeError, match="FILESYSTEM SAFETY TRAP"):
        Path("/md0/movies1/illegal_movie.mkv").touch()

    with pytest.raises(RuntimeError, match="FILESYSTEM SAFETY TRAP"):
        os.makedirs("/md0/tv1/illegal_show/Season 01")

    # Verify tmp_path operations succeed normally
    safe_file = tmp_path / "safe.txt"
    safe_file.write_text("allowed content")
    assert safe_file.read_text() == "allowed content"
    safe_file.unlink()
    assert not safe_file.exists()


# -----------------------------------------------------------------------------
# Test 2: Test Environment Isolation
# -----------------------------------------------------------------------------
def test_isolate_test_environment_step_1_mutates_environment():
    """Step 1: mutate CONFIDENCE_THRESHOLD in os.environ and confirm Settings uses it."""
    os.environ["CONFIDENCE_THRESHOLD"] = "0.99"
    settings = Settings()
    assert settings.general.confidence_threshold == 0.99


def test_isolate_test_environment_step_2_reverts_to_clean_defaults():
    """Step 2: verify isolate_test_environment restored os.environ and clean defaults."""
    assert os.environ.get("CONFIDENCE_THRESHOLD") != "0.99"
    assert "CONFIDENCE_THRESHOLD" not in os.environ
    settings = Settings()
    assert settings.general.confidence_threshold == 0.75
    assert settings.general.worker_count == 4


# -----------------------------------------------------------------------------
# Test 3: /api/explorer/set-destination Latent NameError Fix
# -----------------------------------------------------------------------------
def test_explorer_set_destination_does_not_raise_name_error(isolated_web_env):
    """Verify /api/explorer/set-destination returns 200 without NameError."""
    client, settings, engine, downloads, movies, shows, _ = isolated_web_env

    resp = client.post(
        "/api/explorer/set-destination",
        json={"show_idx": 0, "destination": "/custom/destination/folder"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert data.get("destination") == "/custom/destination/folder"
    assert data.get("success") is True

    # Check validation for missing parameters
    bad_resp = client.post("/api/explorer/set-destination", json={"show_idx": 0})
    assert bad_resp.status_code == 400


# -----------------------------------------------------------------------------
# Test 4: Read-Only File Inspection Does Not Inflate item_count
# -----------------------------------------------------------------------------
def test_get_files_does_not_inflate_library_item_count(isolated_web_env):
    """Verify GET /api/files does not inflate LibraryItem.item_count on repeated calls."""
    client, settings, engine, downloads, movies, shows, _ = isolated_web_env

    # 1. Place a show episode in downloads
    test_file = downloads / "Breaking.Bad.S01E01.1080p.mkv"
    test_file.write_text("media bytes")

    # Seed an existing library item with initial count 5
    with get_db_session(engine) as session:
        record_detected_item(
            session,
            settings,
            "Breaking Bad",
            "tv",
            destination_folder=str(shows / "Breaking Bad"),
            delta_count=5,
        )

    # Query before calling /api/files
    with get_db_session(engine) as session:
        item_before = (
            session.query(LibraryItem).filter_by(title="Breaking Bad", category="tv").first()
        )
        assert item_before is not None
        assert item_before.item_count == 5

    # 2. Call GET /api/files repeatedly (5 times)
    for _ in range(5):
        resp = client.get("/api/files")
        assert resp.status_code == 200

    # 3. Verify item_count remained 5 and was NOT inflated
    with get_db_session(engine) as session:
        item_after = (
            session.query(LibraryItem).filter_by(title="Breaking Bad", category="tv").first()
        )
        assert item_after is not None
        assert item_after.item_count == 5


# -----------------------------------------------------------------------------
# Test 5: /api/files/scan Alias Routes (GET & POST)
# -----------------------------------------------------------------------------
def test_api_files_scan_alias_get_and_post(isolated_web_env):
    """Verify GET /api/files/scan and POST /api/files/scan return HTTP 200 with
    identical data to GET /api/files.
    """
    client, settings, engine, downloads, movies, shows, _ = isolated_web_env

    (downloads / "Severance.S01E01.mkv").write_text("dummy video")
    (movies / "Inception (2010)").mkdir(parents=True, exist_ok=True)
    (movies / "Inception (2010)" / "Inception (2010).mkv").write_text("dummy movie")

    resp_base = client.get("/api/files")
    assert resp_base.status_code == 200
    base_data = resp_base.json()

    resp_scan_get = client.get("/api/files/scan")
    assert resp_scan_get.status_code == 200
    assert resp_scan_get.json() == base_data

    resp_scan_post = client.post("/api/files/scan")
    assert resp_scan_post.status_code == 200
    assert resp_scan_post.json() == base_data

    # Check top-level contract keys
    assert "downloads" in base_data
    assert "movies" in base_data
    assert "shows" in base_data


# -----------------------------------------------------------------------------
# Bonus Test: External Network Trap
# -----------------------------------------------------------------------------
def test_block_external_network_trap():
    """Verify block_external_network prevents outbound external connections."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(RuntimeError, match="NETWORK ACCESS TRAP"):
        s.connect(("8.8.8.8", 53))
