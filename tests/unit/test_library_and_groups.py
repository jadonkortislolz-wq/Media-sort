from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from media_sorter.config import Settings
from media_sorter.db import get_db_session, init_db
from media_sorter.library import (
    clean_show_title,
    get_known_shows,
    list_library_items,
    match_known_show,
    record_detected_item,
    sync_library_from_disk,
)
from media_sorter.server import cluster_unsure_files, create_app, inspect_downloads_folder


@pytest.fixture
def library_env(tmp_path: Path):
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

    return client, settings, engine, downloads, movies, shows


def test_library_sync_and_show_memory(library_env):
    client, settings, engine, downloads, movies, shows = library_env

    # 1. Populate disk with shows and movies
    dexter_dir = shows / "Dexter" / "Season 01"
    dexter_dir.mkdir(parents=True)
    (dexter_dir / "Dexter - S01E01.mkv").write_bytes(b"\x00" * 100)
    (dexter_dir / "Dexter - S01E02.mkv").write_bytes(b"\x00" * 100)

    breaking_bad_dir = shows / "Breaking Bad" / "Season 01"
    breaking_bad_dir.mkdir(parents=True)
    (breaking_bad_dir / "Breaking Bad - S01E01.mkv").write_bytes(b"\x00" * 100)

    movie_dir = movies / "Inception (2010)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Inception (2010).mkv").write_bytes(b"\x00" * 100)

    with get_db_session(engine) as session:
        sync_res = sync_library_from_disk(session, settings)
        assert sync_res["shows_synced"] == 2
        assert sync_res["movies_synced"] == 1

        # 2. Check list_library_items
        all_items = list_library_items(session)
        assert all_items["total_shows"] == 2
        assert all_items["total_movies"] == 1

        shows_only = list_library_items(session, category="tv")
        assert len(shows_only["shows"]) == 2
        assert len(shows_only["movies"]) == 0

        movies_only = list_library_items(session, category="movie")
        assert len(movies_only["movies"]) == 1

        search_res = list_library_items(session, search="dexter")
        assert len(search_res["shows"]) == 1
        assert search_res["shows"][0]["title"] == "Dexter"

        # 3. Test known shows matching
        known_shows = get_known_shows(session)
        assert len(known_shows) == 2

        matched = match_known_show("Dexter's Kill Room Extra.mkv", known_shows)
        assert matched is not None
        assert matched["title"] == "Dexter"

        matched_bb = match_known_show("Breaking.Bad.Behind.The.Scenes.mp4", known_shows)
        assert matched_bb is not None
        assert matched_bb["title"] == "Breaking Bad"

        assert match_known_show("Unrelated Movie.mkv", known_shows) is None


def test_cluster_unsure_files(library_env):
    client, settings, engine, downloads, movies, shows = library_env

    unsure_files = [
        # Subfolder group (Folder: Dexter Extras)
        {"name": "Interview.mkv", "relative_path": "Dexter Extras/Interview.mkv", "detected_type": "other"},
        {"name": "Behind Scenes.mkv", "relative_path": "Dexter Extras/Behind Scenes.mkv", "detected_type": "other"},
        # Common prefix group (Blood, Guts and Body Parts)
        {"name": "Blood, Guts and Body Parts The Blood.mkv", "relative_path": "Blood, Guts and Body Parts The Blood.mkv", "detected_type": "other"},
        {"name": "Blood, Guts and Body Parts The Props.mkv", "relative_path": "Blood, Guts and Body Parts The Props.mkv", "detected_type": "other"},
        # Same title group (Inception)
        {"name": "Inception.1080p.mkv", "relative_path": "Inception.1080p.mkv", "detected_type": "movie"},
        {"name": "Inception.720p.mp4", "relative_path": "Inception.720p.mp4", "detected_type": "movie"},
        # Standalone single file
        {"name": "Solo Movie (2021).mkv", "relative_path": "Solo Movie (2021).mkv", "detected_type": "movie"},
    ]

    groups, singles = cluster_unsure_files(unsure_files, settings)

    group_names = [g["group_name"] for g in groups]
    assert "Dexter Extras" in group_names
    assert any("Blood" in gn for gn in group_names)

    single_names = [s["name"] for s in singles]
    assert "Solo Movie (2021).mkv" in single_names


def test_show_memory_routing_in_inspection(library_env):
    client, settings, engine, downloads, movies, shows = library_env

    # Record "Dexter" into library
    with get_db_session(engine) as session:
        record_detected_item(session, settings, "Dexter", "tv")

    # Add a non-standard extra in downloads matching Dexter
    dexter_extra = downloads / "Dexter's Kill Room Extra.mkv"
    dexter_extra.write_bytes(b"\x00" * 100)

    # Inspect downloads with engine
    inspection = inspect_downloads_folder(downloads, settings, engine=engine)
    assert len(inspection["shows"]) == 1
    assert inspection["shows"][0]["show_name"] == "Dexter"
    assert len(inspection["shows"][0]["files"]) == 1


def test_library_and_sort_group_api(library_env):
    client, settings, engine, downloads, movies, shows = library_env

    # 1. API: Rescan Library
    dexter_dir = shows / "Dexter" / "Season 01"
    dexter_dir.mkdir(parents=True)
    (dexter_dir / "Dexter - S01E01.mkv").write_bytes(b"\x00" * 100)

    rescan_resp = client.post("/api/library/rescan")
    assert rescan_resp.status_code == 200
    assert rescan_resp.json()["shows_synced"] >= 1

    # 2. API: GET /api/library
    lib_resp = client.get("/api/library")
    assert lib_resp.status_code == 200
    lib_data = lib_resp.json()
    assert lib_data["total_shows"] >= 1

    # 3. API: POST /api/files/sort-group
    group_sub = downloads / "My Special Show"
    group_sub.mkdir()
    f1 = group_sub / "Episode 1.mkv"
    f2 = group_sub / "Episode 2.mkv"
    f1.write_bytes(b"\x00" * 100)
    f2.write_bytes(b"\x00" * 100)

    sort_group_resp = client.post("/api/files/sort-group", json={
        "group_name": "My Special Show",
        "group_type": "folder",
        "category": "tv",
        "title": "My Special Show",
        "relative_paths": ["My Special Show/Episode 1.mkv", "My Special Show/Episode 2.mkv"],
    })
    assert sort_group_resp.status_code == 200
    sort_data = sort_group_resp.json()
    assert sort_data["status"] == "ok"
    assert sort_data["moved_files"] == 2

    # Verify files moved to shows directory
    dest_show = shows / "My Special Show"
    assert dest_show.exists()

    # Verify newly sorted show was automatically recorded in the library
    lib_after = client.get("/api/library?search=Special").json()
    assert len(lib_after["shows"]) == 1
    assert lib_after["shows"][0]["title"] == "My Special Show"
