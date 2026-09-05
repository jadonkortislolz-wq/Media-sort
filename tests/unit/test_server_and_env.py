from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from media_sorter.config import Settings
from media_sorter.db import init_db
from media_sorter.server import create_app


@pytest.fixture
def web_env(tmp_path: Path):
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

    return client, settings, downloads, movies, shows, test_env_file


def test_web_status_and_dashboard(web_env):
    client, settings, downloads, movies, shows, test_env_file = web_env
    # 1. HTML Dashboard renders cleanly
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Media Sorter" in resp.text
    assert "Folder Explorer" in resp.text

    # 2. Status API returns paths
    status_resp = client.get("/api/status")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["status"] == "online"
    assert data["downloads_dir"] == str(downloads)
    assert data["movies_dir"] == str(movies)
    assert data["shows_dir"] == str(shows)


def test_web_sample_generation_and_sorting(web_env):
    client, settings, downloads, movies, shows, test_env_file = web_env

    # 1. Generate sample downloads
    sample_resp = client.post("/api/files/test-sample")
    assert sample_resp.status_code == 200
    sample_data = sample_resp.json()
    assert len(sample_data["files"]) >= 5

    # Verify files in downloads folder via API
    files_resp = client.get("/api/files")
    assert files_resp.status_code == 200
    files_data = files_resp.json()
    assert len(files_data["downloads"]["files"]) >= 5

    # 2. Trigger Sorter Live execution via Web API
    run_resp = client.post("/api/run", json={"dry_run": False})
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["moved_files"] >= 3

    # Verify files moved to movies and shows
    files_after = client.get("/api/files").json()
    assert len(files_after["movies"]["files"]) >= 2
    assert len(files_after["shows"]["files"]) >= 2

    # 3. Trigger Rollback via Web API
    rb_resp = client.post("/api/rollback", json={"batch_id": run_data["batch_id"]})
    assert rb_resp.status_code == 200
    rb_data = rb_resp.json()
    assert rb_data["reverted_files"] >= 3

    # Verify files restored to downloads folder
    files_reverted = client.get("/api/files").json()
    assert len(files_reverted["downloads"]["files"]) >= 4

    # 4. Test deleting a single download file via Web API
    file_to_del = sample_data["files"][0]
    del_resp = client.delete(f"/api/files/download?name={file_to_del}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"
    files_post_del = client.get("/api/files").json()
    assert len(files_post_del["downloads"]["files"]) == len(files_reverted["downloads"]["files"]) - 1


def test_web_settings_update(web_env, tmp_path: Path):
    client, settings, downloads, movies, shows, test_env_file = web_env
    new_downloads = tmp_path / "new_downloads"
    new_movies = tmp_path / "new_movies"

    update_payload = {
        "downloads_dir": str(new_downloads),
        "movies_dir": str(new_movies),
        "dry_run": True,
        "confidence_threshold": 0.80,
    }
    resp = client.post("/api/settings", json=update_payload)
    assert resp.status_code == 200

    # Verify updated settings
    settings_resp = client.get("/api/settings")
    assert settings_resp.status_code == 200
    s_data = settings_resp.json()
    assert s_data["downloads_dir"] == str(new_downloads)
    assert s_data["movies_dir"] == str(new_movies)
    assert s_data["dry_run"] is True
    assert s_data["confidence_threshold"] == 0.80

    # Verify test_env_file was written
    assert test_env_file.is_file()
    content = test_env_file.read_text(encoding="utf-8")
    assert str(new_downloads) in content
    assert str(new_movies) in content


def test_web_restart_endpoint(web_env, monkeypatch):
    client, settings, downloads, movies, shows, test_env_file = web_env
    # Prevent background task from exiting test process
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setattr("os._exit", lambda _: None)
    monkeypatch.setattr("os.execv", lambda *_: None)

    resp = client.post("/api/restart")
    assert resp.status_code == 200
    assert resp.json()["status"] == "restarting"


def test_web_clear_batches_endpoint(web_env):
    client, settings, downloads, movies, shows, test_env_file = web_env
    # Create sample files and run sort
    client.post("/api/files/test-sample")
    run_resp = client.post("/api/run", json={"dry_run": False})
    assert run_resp.status_code == 200

    batches = client.get("/api/batches").json()
    assert len(batches) >= 1

    # Clear batches
    clear_resp = client.post("/api/batches/clear")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["status"] == "cleared"

    # Verify batches are now empty
    batches_after = client.get("/api/batches").json()
    assert len(batches_after) == 0

