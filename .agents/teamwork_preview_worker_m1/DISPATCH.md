## 2026-09-05T23:53:52Z
Your working directory is: /md0/media-sorter/.agents/teamwork_preview_worker_m1
The authoritative original request is: /md0/media-sorter/.agents/ORIGINAL_REQUEST.md
You MUST read /md0/media-sorter/.agents/ORIGINAL_REQUEST.md before starting work.

Context & Prior Explorer Findings:
- Read /md0/media-sorter/.agents/orchestrator_2/PROJECT.md
- Read /md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_2/handoff.md (specifically sections 1.3, 4.1, 5.2, 5.3)
- Read /md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_3/handoff.md (specifically sections 1.3.1, 1.6, 2.1, 4.0)

Write Ownership (Exclusive):
- tests/conftest.py
- src/media_sorter/server.py
- tests/unit/test_safety_and_defects.py
You MUST NOT edit any other files.

Mission:
Implement Milestone 1: Filesystem Safety Traps, Test Environment Isolation & Server Defect Remediation.

Tasks:
1. Establish root `tests/conftest.py`:
   - `protect_production_filesystem` (fixture with `autouse=True`, `scope="session"`):
     Active safety trap that monkeypatches filesystem modification operations in `os`, `shutil`, `pathlib.Path`, and `open` (for write/append/create modes).
     Inspects all target paths: if any path resolves into or is inside `/md0/jdownloads`, `/md0/movies1`, or `/md0/tv1`, raises:
     `RuntimeError("FILESYSTEM SAFETY TRAP: Forbidden write/delete operation targeting production path '{target}' in test execution!")`.
     Ensure tests using `tmp_path` continue working cleanly.
   - `isolate_test_environment` (fixture with `autouse=True`, `scope="function"`):
     Saves `os.environ` before test and restores it after. Strips any existing `CONFIDENCE_THRESHOLD`, `DOWNLOADS_DIR`, `MOVIES_DIR`, `SHOWS_DIR`, `ANIME_DIR`, `SOURCE_DIR`, `TV_DIR`, `DRY_RUN`, `ACTION`, and `MEDIA_SORTER_*` variables so `Settings()` initializes with clean test defaults and prevents cross-test contamination.
   - `block_external_network` (fixture with `autouse=True`, `scope="session"`):
     Monkeypatches `socket.socket.connect` to prevent outbound internet network requests during tests (allow loopback/localhost and unix domain sockets).

2. Fix Latent Server Defects in `src/media_sorter/server.py`:
   - Line 1453 in `/api/explorer/set-destination`:
     Remove or guard the reference to `currentExplorerShows` (which only exists in frontend JS and causes runtime NameError in Python). Return `{"status": "ok", "destination": destination}`.
   - Line 581 in `inspect_downloads_folder`:
     Remove `record_detected_item(session, settings, show_item["show_name"], "tv", ..., delta_count=show_item["count"])`. File inspection is a read-only operation and must NOT cumulatively inflate `LibraryItem.item_count` in the database.
   - Add alias route for `/api/files/scan` (supporting both GET and POST):
     `@app.get("/api/files/scan")` and `@app.post("/api/files/scan")` delegating to `get_files()` so callers expecting R3's `/api/files/scan` endpoint receive identical file inspection data with HTTP 200.

3. Establish `tests/unit/test_safety_and_defects.py`:
   - Test 1: Verify `protect_production_filesystem` trap triggers `RuntimeError` on attempted write or delete in `/md0/jdownloads/illegal.txt`.
   - Test 2: Verify `isolate_test_environment` prevents cross-test contamination (e.g. mutating `CONFIDENCE_THRESHOLD` in one test does not leak to another test).
   - Test 3: Verify `/api/explorer/set-destination` does not raise `NameError`.
   - Test 4: Verify `GET /api/files` does not inflate `LibraryItem.item_count` on repeated calls.
   - Test 5: Verify `GET /api/files/scan` and `POST /api/files/scan` return HTTP 200 with identical data to `GET /api/files`.

4. Verification:
   Run `.venv/bin/pytest tests/` to confirm all 75 baseline tests plus your new safety tests pass 100% with zero regressions.
