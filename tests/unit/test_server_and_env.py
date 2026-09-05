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


def test_folder_explorer_excludes_txt_files(web_env):
    client, settings, downloads, movies, shows, test_env_file = web_env
    from media_sorter.server import inspect_downloads_folder, list_files_in_dir

    # Create real media files
    (downloads / "Movie.2024.1080p.mkv").write_bytes(b"\x1aE\xdf\xa3" + b"\x00" * 100)
    (shows / "Show.S01E01.mkv").write_bytes(b"\x1aE\xdf\xa3" + b"\x00" * 100)

    # Create various .txt files in downloads and destination folders
    (downloads / "Movie.2024.txt").write_text("info text")
    (downloads / "readme.txt").write_text("readme text")
    (downloads / "NOTES.TXT").write_text("notes text")
    sub_dir = downloads / "Show.Release"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "tracker.txt").write_text("tracker info")
    (shows / "show_notes.txt").write_text("notes")

    # 1. inspect_downloads_folder must exclude all .txt files
    inspected = inspect_downloads_folder(downloads, settings)
    for f in inspected["files"]:
        assert not f["name"].lower().endswith(".txt")
    for s in inspected["shows"]:
        for f in s["files"]:
            assert not f["name"].lower().endswith(".txt")
    for f in inspected["singles"]:
        assert not f["name"].lower().endswith(".txt")

    # 2. list_files_in_dir must exclude .txt files
    shows_listed = list_files_in_dir(shows)
    for f in shows_listed:
        assert not f["name"].lower().endswith(".txt")

    # 3. GET /api/files endpoint must exclude .txt files from folder explorer response
    res = client.get("/api/files")
    assert res.status_code == 200
    data = res.json()
    downloads_data = data["downloads"]
    assert any(f["name"] == "Movie.2024.1080p.mkv" for f in downloads_data["files"])
    assert not any(f["name"].lower().endswith(".txt") for f in downloads_data["files"])
    assert not any(f["name"].lower().endswith(".txt") for f in downloads_data["singles"])


def test_folder_explorer_excludes_srt_files(web_env):
    client, settings, downloads, movies, shows, test_env_file = web_env
    from media_sorter.server import inspect_downloads_folder, list_files_in_dir

    # Create real media files alongside .srt subtitles
    (downloads / "Avatar.2009.1080p.mkv").write_bytes(b"\x1aE\xdf\xa3" + b"\x00" * 100)
    (downloads / "Avatar.2009.1080p.en.srt").write_text("1\n00:00:01 --> 00:00:03\nSubtitles\n")
    (downloads / "random_track.SRT").write_text("sub")

    sub_dir = downloads / "Show.Episode.Folder"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "Episode 01.mkv").write_bytes(b"\x1aE\xdf\xa3" + b"\x00" * 100)
    (sub_dir / "Episode 01.srt").write_text("sub")
    (shows / "Show.S01E01.en.srt").write_text("sub")

    # 1. inspect_downloads_folder must exclude all .srt files
    inspected = inspect_downloads_folder(downloads, settings)
    for f in inspected["files"]:
        assert not f["name"].lower().endswith(".srt")
    for s in inspected["shows"]:
        for f in s["files"]:
            assert not f["name"].lower().endswith(".srt")
    for g in inspected["unsure_groups"]:
        for f in g["files"]:
            assert not f["name"].lower().endswith(".srt")
    for f in inspected["singles"]:
        assert not f["name"].lower().endswith(".srt")

    # 2. list_files_in_dir must exclude .srt files
    shows_listed = list_files_in_dir(shows)
    for f in shows_listed:
        assert not f["name"].lower().endswith(".srt")

    # 3. GET /api/files endpoint must exclude .srt files from folder explorer response
    res = client.get("/api/files")
    assert res.status_code == 200
    data = res.json()
    downloads_data = data["downloads"]
    assert any(f["name"] == "Avatar.2009.1080p.mkv" for f in downloads_data["files"])
    assert not any(f["name"].lower().endswith(".srt") for f in downloads_data["files"])
    assert not any(f["name"].lower().endswith(".srt") for f in downloads_data["singles"])
    assert not any(f["name"].lower().endswith(".srt") for s in downloads_data["shows"] for f in s["files"])
    assert not any(f["name"].lower().endswith(".srt") for g in downloads_data["unsure_groups"] for f in g["files"])


def test_delete_download_file_cleans_txt_and_parent_dir(web_env):
    client, settings, downloads, movies, shows, test_env_file = web_env

    # Setup a subfolder in downloads with a file, a companion .txt, and an extra .txt
    sub_dir = downloads / "Custom.Release.Folder"
    sub_dir.mkdir(parents=True, exist_ok=True)
    media = sub_dir / "sample.mkv"
    media.write_text("sample")
    companion_txt = sub_dir / "sample.txt"
    companion_txt.write_text("companion")
    extra_txt = sub_dir / "release.txt"
    extra_txt.write_text("release note")

    # Delete sample.mkv via API
    del_res = client.delete(f"/api/files/download?name=Custom.Release.Folder/sample.mkv")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Verify media, companion .txt, extra .txt, and empty parent subfolder are removed
    assert not media.exists()
    assert not companion_txt.exists()
    assert not extra_txt.exists()
    assert not sub_dir.exists()
    assert downloads.exists()


def test_rollback_all_api(web_env):
    client, settings, downloads, movies, shows, test_env_file = web_env

    # 1. Generate sample downloads and sort
    client.post("/api/files/test-sample")
    client.post("/api/run", json={"dry_run": False})

    # Add extra file and sort again to form a second batch
    f = downloads / "Extra.Film.2022.mkv"
    f.write_text("extra movie")
    client.post("/api/run", json={"dry_run": False})

    # Call rollback all
    rb_res = client.post("/api/rollback/all")
    assert rb_res.status_code == 200
    assert rb_res.json()["status"] == "ok"
    assert rb_res.json()["reverted_files"] >= 4

    # Verify files restored to downloads
    files_res = client.get("/api/files").json()
    assert len(files_res["downloads"]["files"]) >= 4


def test_manual_sort_file_api(web_env):
    client, settings, downloads, movies, shows, test_env_file = web_env

    # Test sorting as movie with custom title & year
    movie_file = downloads / "ambiguous_movie_file.mkv"
    movie_file.write_text("movie payload")

    res_movie = client.post("/api/files/manual-sort", json={
        "relative_path": "ambiguous_movie_file.mkv",
        "category": "movie",
        "title": "Interstellar",
        "year": 2014,
    })
    assert res_movie.status_code == 200
    assert not movie_file.exists()
    dest_movie = movies / "Interstellar (2014)" / "Interstellar (2014).mkv"
    assert dest_movie.exists()

    # Test sorting as TV show with custom title, season, episode
    tv_file = downloads / "random_episode.mkv"
    tv_file.write_text("tv payload")

    res_tv = client.post("/api/files/manual-sort", json={
        "relative_path": "random_episode.mkv",
        "category": "tv",
        "title": "Succession",
        "season": 3,
        "episode": 5,
    })
    assert res_tv.status_code == 200
    assert not tv_file.exists()
    dest_tv = shows / "Succession" / "Season 03" / "Succession - S03E05.mkv"
    assert dest_tv.exists()


def test_quarantine_resolve_and_undo_api(web_env):
    client, settings, downloads, movies, shows, test_env_file = web_env
    from media_sorter.db import get_db_session
    from media_sorter.models import QuarantineRecord, QuarantineStatus
    from media_sorter.quarantine import QuarantineManager

    quar_file = downloads / "unknown_sample.xyz"
    quar_file.write_text("quarantine payload")

    # Manually insert pending record
    engine = init_db(db_path=settings.database.path)
    with get_db_session(engine) as s:
        qm = QuarantineManager(s)
        rec = QuarantineRecord(
            src=str(quar_file),
            suggested_category="movie",
            confidence=0.45,
            reason="Unrecognized format",
            status=QuarantineStatus.PENDING.value,
        )
        s.add(rec)
        s.commit()
        item_id = rec.id

    # 1. GET /api/quarantine returns pending and resolved
    q_res = client.get("/api/quarantine")
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert len(q_data["pending"]) == 1
    assert q_data["pending"][0]["id"] == item_id
    assert len(q_data["resolved"]) == 0

    # 2. POST /api/quarantine/{id}/resolve with custom TV show title
    res_resolve = client.post(f"/api/quarantine/{item_id}/resolve", json={
        "category": "tv",
        "title": "Severance",
        "season": 1,
        "episode": 1,
    })
    assert res_resolve.status_code == 200
    assert not quar_file.exists()
    dest_tv = shows / "Severance" / "Season 01" / "Severance - S01E01.xyz"
    assert dest_tv.exists()

    # Verify GET /api/quarantine reflects resolved item
    q_res2 = client.get("/api/quarantine").json()
    assert len(q_res2["pending"]) == 0
    assert len(q_res2["resolved"]) == 1

    # 3. POST /api/quarantine/{id}/undo restores file to src and marks PENDING
    res_undo = client.post(f"/api/quarantine/{item_id}/undo")
    assert res_undo.status_code == 200
    assert res_undo.json()["status"] == "undone"

    assert quar_file.exists()
    assert not dest_tv.exists()

    q_res3 = client.get("/api/quarantine").json()
    assert len(q_res3["pending"]) == 1
    assert len(q_res3["resolved"]) == 0

    # 4. POST /api/quarantine/{id}/undo on pending item unflags/deletes it
    res_unflag = client.post(f"/api/quarantine/{item_id}/undo")
    assert res_unflag.status_code == 200
    q_res4 = client.get("/api/quarantine").json()
    assert len(q_res4["pending"]) == 0


def test_inspect_downloads_movie_subfolder_classified_as_movie(web_env):
    client, settings, downloads, movies, shows, test_env_file = web_env

    # 1. Torrent-style movie inside a subfolder
    movie_folder = downloads / "The.Dark.Knight.2008.1080p.BluRay.x264-ROVERS"
    movie_folder.mkdir(parents=True, exist_ok=True)
    movie_file = movie_folder / "The.Dark.Knight.2008.1080p.BluRay.x264-ROVERS.mkv"
    movie_file.write_text("movie data")

    # 2. Movie inside clean folder
    opp_folder = downloads / "Oppenheimer (2023)"
    opp_folder.mkdir(parents=True, exist_ok=True)
    opp_file = opp_folder / "Oppenheimer.2023.2160p.mkv"
    opp_file.write_text("oppenheimer data")

    # 3. Legitimate TV show
    tv_folder = downloads / "Breaking Bad Season 1"
    tv_folder.mkdir(parents=True, exist_ok=True)
    tv_file = tv_folder / "Breaking.Bad.S01E01.Pilot.mkv"
    tv_file.write_text("tv show data")

    # Query folder explorer
    files_res = client.get("/api/files").json()
    dl_info = files_res["downloads"]

    # Movies must be in singles, not in shows
    single_rel_paths = [s["relative_path"] for s in dl_info["singles"]]
    assert "The.Dark.Knight.2008.1080p.BluRay.x264-ROVERS/The.Dark.Knight.2008.1080p.BluRay.x264-ROVERS.mkv" in single_rel_paths
    assert "Oppenheimer (2023)/Oppenheimer.2023.2160p.mkv" in single_rel_paths

    for s in dl_info["singles"]:
        if "The.Dark.Knight" in s["relative_path"]:
            assert s["detected_type"] == "movie"
            assert "The Dark Knight" in s["believed_title"]
            assert str(movies) in s["believed_destination"]
        if "Oppenheimer" in s["relative_path"]:
            assert s["detected_type"] == "movie"
            assert "Oppenheimer" in s["believed_title"]
            assert str(movies) in s["believed_destination"]

    # Shows must only contain Breaking Bad, not the movies
    show_names = [show["show_name"] for show in dl_info["shows"]]
    assert "Breaking Bad" in show_names
    assert "The Dark Knight" not in show_names
    assert "The.Dark.Knight.2008.1080p.BluRay.x264-ROVERS" not in show_names
    assert "Oppenheimer" not in show_names


def test_quarantine_bulk_resolve_and_bulk_undo_api(web_env):
    client, settings, downloads, movies, shows, test_env_file = web_env
    from media_sorter.db import get_db_session
    from media_sorter.models import QuarantineRecord, QuarantineStatus
    from media_sorter.quarantine import QuarantineManager

    f1 = downloads / "Unknown.Movie.2021.1080p.mkv"
    f1.write_text("movie1 payload")
    f2 = downloads / "Another.Film.2023.720p.mkv"
    f2.write_text("movie2 payload")
    f3 = downloads / "Mystery.File.xyz"
    f3.write_text("mystery payload")

    engine = init_db(db_path=settings.database.path)
    with get_db_session(engine) as s:
        r1 = QuarantineRecord(src=str(f1), suggested_category="movie", confidence=0.4, reason="Low confidence", status=QuarantineStatus.PENDING.value)
        r2 = QuarantineRecord(src=str(f2), suggested_category="movie", confidence=0.4, reason="Low confidence", status=QuarantineStatus.PENDING.value)
        r3 = QuarantineRecord(src=str(f3), suggested_category="unknown", confidence=0.1, reason="Unrecognized format", status=QuarantineStatus.PENDING.value)
        s.add_all([r1, r2, r3])
        s.commit()
        id1, id2, id3 = r1.id, r2.id, r3.id

    # 1. Bulk resolve id1 and id2 as movie
    res_b = client.post("/api/quarantine/bulk-resolve", json={
        "item_ids": [id1, id2],
        "category": "movie"
    })
    assert res_b.status_code == 200
    assert res_b.json()["resolved_count"] == 2
    assert not f1.exists()
    assert not f2.exists()
    assert f3.exists()

    # 2. Bulk unflag id3
    res_u = client.post("/api/quarantine/bulk-undo", json={
        "item_ids": [id3],
        "scope": "pending"
    })
    assert res_u.status_code == 200
    assert res_u.json()["undone_count"] == 1
    assert f3.exists()  # Unflag leaves file in source

    # Verify id3 is deleted from quarantine
    q_data = client.get("/api/quarantine").json()
    assert len(q_data["pending"]) == 0
    assert len(q_data["resolved"]) == 2

    # 3. Bulk undo all resolved items
    res_all_undo = client.post("/api/quarantine/bulk-undo", json={
        "scope": "resolved"
    })
    assert res_all_undo.status_code == 200
    assert res_all_undo.json()["undone_count"] == 2
    assert f1.exists()
    assert f2.exists()

    q_data_restored = client.get("/api/quarantine").json()
    assert len(q_data_restored["pending"]) == 2
    assert len(q_data_restored["resolved"]) == 0


def test_sort_show_endpoint_and_rollback(web_env):
    client, settings, downloads, movies, shows, test_env_file = web_env

    # Create episodic show files and an unrelated file
    ep1 = downloads / "Naruto Episode 001 Enter Naruto Uzumaki!.mkv"
    ep2 = downloads / "Naruto Episode 002 My Name is Konohamaru!.mkv"
    movie = downloads / "Inception (2010).mkv"

    header = b"\x1aE\xdf\xa3" + b"\x00" * 300
    ep1.write_bytes(header)
    ep2.write_bytes(header)
    movie.write_bytes(header)

    # 1. Sort show specifically
    res = client.post("/api/files/sort-show", json={
        "show_name": "Naruto"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["moved_files"] == 2
    assert data["show_name"] == "Naruto"

    # Naruto episodes moved, movie remains in downloads
    assert not ep1.exists()
    assert not ep2.exists()
    assert movie.exists()

    # Destination directory contains organized show
    naruto_dir = shows / "Naruto"
    assert naruto_dir.exists()
    organized_eps = list(naruto_dir.rglob("*.mkv"))
    assert len(organized_eps) == 2

    # 2. Rollback the show batch
    batch_id = data["batch_id"]
    rb_res = client.post("/api/rollback", json={"batch_id": batch_id})
    assert rb_res.status_code == 200
    assert rb_res.json()["reverted_files"] == 2

    # Files restored to downloads
    assert ep1.exists()
    assert ep2.exists()

    # 3. Non-existent show returns 404
    err_res = client.post("/api/files/sort-show", json={
        "show_name": "NonExistentShow"
    })
    assert err_res.status_code == 404






