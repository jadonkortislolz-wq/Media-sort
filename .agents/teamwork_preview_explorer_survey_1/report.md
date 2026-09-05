# Comprehensive Codebase Survey: Architecture, Server Monolith & Test Baseline

**Survey Date:** 2026-09-05  
**Surveyor:** Explorer 1 (Codebase Architecture & Server Monolith & Test Baseline)  
**Target Repository:** `/md0/media-sorter`  
**Integrity Mode:** Development  

---

## Executive Summary

Media Sorter is a Python application (version 1.0.7) built to automate media collection organization (movies, TV shows, anime, music, audiobooks, podcasts, archives) with transactional safety, Write-Ahead Logging (WAL) SQLite persistence, automated rollback capabilities, and an interactive single-page web dashboard.

The application currently has **75 baseline automated tests** that pass with 100% success in 1.29s. However, the server architecture exhibits extreme monolithic coupling: **`src/media_sorter/server.py` contains 4,915 lines of code—over 51% of the entire codebase**. Inside this single file, Pydantic request models, folder inspection algorithms, heuristic string clustering, external artwork network querying (TVmaze), 27 REST API endpoints, database session operations, and over **3,400 lines of raw HTML, CSS, theme variables, and client-side JavaScript** are concatenated together in a single Python file.

This survey establishes the complete baseline layout, server structure, REST API contract, web dashboard components, and test environment to guide Phase 2 (Decomposition & Decoupling).

---

## 1. Full Directory and File Layout

```
/md0/media-sorter/
├── pyproject.toml                     # Poetry project configuration & dependencies
├── alembic.ini                        # Alembic migration configuration
├── alembic/                           # Database migration scripts
│   ├── env.py                         # Migration runner environment
│   ├── script.py.mako                 # Migration revision template
│   └── versions/
│       └── a3cc170248be_initial_schema.py # Initial database schema
├── Dockerfile                         # Container build definition
├── docker-compose.yml                 # Multi-container orchestration
├── ecosystem.config.js                # PM2 process manager configuration (runs .venv/bin/media-sorter server)
├── media-sorter.service               # Systemd unit file
├── config.example.yaml                # Example YAML configuration
├── config.example.toml                # Example TOML configuration
├── README.md                          # Project documentation
├── CHANGELOG.md                       # Version changelog
├── LICENSE                            # MIT License
├── ORIGINAL_REQUEST.md                # Project requirements and acceptance criteria
├── media_sorter.db                    # Active SQLite database (WAL mode)
├── media_sorter.db-wal                # SQLite Write-Ahead Log
├── media_sorter.db-shm                # SQLite Shared Memory index
├── media_sorter.lock                  # Process locking file for concurrency control
├── media_sorter_posters.json          # Disk cache for show posters (local & TVmaze)
├── sample_dry_run_report.json         # Example batch execution report
├── incoming/                          # Sample incoming media directory
├── downloads/                         # Default source media directory
├── movies/                            # Default organized movies directory
├── shows/                             # Default organized TV shows directory
├── organized/                         # Default organized root (Photos, Quarantine, subtitle)
│   ├── metadata/
│   ├── Photos/
│   ├── Quarantine/
│   └── subtitle/
├── .venv/                             # Python 3.14.3 virtual environment
├── src/media_sorter/                  # Core package source code (9,532 total lines)
│   ├── __init__.py                    # Version constant: __version__ = "1.0.7" (4 lines)
│   ├── analyzer.py                    # Media file metadata extraction (539 lines)
│   ├── classifier.py                  # Multi-category confidence classifier (404 lines)
│   ├── cli.py                         # Typer CLI application entry point (339 lines)
│   ├── config.py                      # Pydantic BaseSettings & .env serialization (497 lines)
│   ├── db.py                          # SQLite engine, pragmas & session manager (76 lines)
│   ├── executor.py                    # Atomic execution, rollbacks, locking, cleanup (689 lines)
│   ├── library.py                     # LibraryItem cataloging, sync & show memory (290 lines)
│   ├── models.py                      # SQLAlchemy ORM declarations (184 lines)
│   ├── namer.py                       # File/path templating & filename sanitization (261 lines)
│   ├── notifications.py               # Webhook notification dispatcher (67 lines)
│   ├── providers.py                   # TMDB metadata client & cache (255 lines)
│   ├── quarantine.py                  # QuarantineManager CRUD operations (141 lines)
│   ├── scanner.py                     # Filesystem scanning & filtering (235 lines)
│   ├── server.py                      # Monolithic server, REST API & HTML UI (4,915 lines)
│   ├── sorter.py                      # MediaSorterApp pipeline orchestrator (324 lines)
│   └── tokenizer.py                   # Filename tokenizer for SxxExx, anime tags, years (312 lines)
└── tests/                             # Automated test suite (75 tests across 11 files)
    ├── conftest.py                    # (Not present; fixtures defined per test file)
    ├── integration/
    │   ├── test_end_to_end.py         # End-to-end sorting pipeline integration test (1 test)
    │   └── test_messy_filenames_and_fuzz.py # Parametrized anime/scene tags + Hypothesis fuzzing (7 tests)
    └── unit/
        ├── test_analyzer.py           # FLAC, ID3v2, EXIF, PNG dimensions, archives (5 tests)
        ├── test_classifier.py         # Classification categories, confidence, provider fallbacks (14 tests)
        ├── test_config_and_db.py      # Pydantic settings defaults, YAML load, DB init (3 tests)
        ├── test_executor_and_rollback.py # Dry-run, atomic move, rollback, locking, cleanup (7 tests)
        ├── test_library_and_groups.py # Library sync, show memory, clustering, sort-group API (4 tests)
        ├── test_namer.py              # Path generation, Windows reserved names, sidecar subtitles (6 tests)
        ├── test_quarantine.py         # Quarantine CRUD and undo logic (2 tests)
        ├── test_server_and_env.py     # Server endpoints, exclusions, manual sort, restart (14 tests)
        └── test_tokenizer.py          # Tokenization regexes, anime brackets, multi-episode (12 tests)
```

---

## 2. Server Entry Points and Monolithic Architecture

### 2.1 Server Entry Points

1. **CLI Invocation (`src/media_sorter/cli.py` lines 300–339)**
   ```bash
   media-sorter server [--host 0.0.0.0] [--port 8080] [--config config.yaml]
   ```
   - Invoked directly or via PM2 (`ecosystem.config.js`: `.venv/bin/media-sorter server`).
   - Parses host/port CLI options with fallbacks to `settings.server.host` (default `"0.0.0.0"`) and `settings.server.port` (default `8080`).
   - Imports `from .server import create_app` and launches Uvicorn:
     ```python
     web_app = create_app(settings)
     uvicorn.run(web_app, host=bind_host, port=bind_port, log_level=settings.general.log_level.lower())
     ```

2. **Application Factory (`src/media_sorter/server.py` line 620)**
   ```python
   def create_app(
       settings: Settings,
       engine: Optional[Engine] = None,
       env_path: Path | str = ".env",
   ) -> FastAPI:
   ```
   - Creates the `FastAPI` instance with lifecycle management (`lifespan`).
   - Background worker: Spawns `auto_sort_worker()` running `MediaSorterApp.run()` if `settings.general.scan_interval_seconds > 0`.
   - Initial Library Sync: Triggers `initial_library_sync()` in an executor thread on startup.
   - Registers all 27 REST routes and the dashboard UI route.

### 2.2 Monolithic Breakdown of `src/media_sorter/server.py`

`server.py` has **4,915 lines**. It is partitioned into four major layers:

| Line Range | Size (Lines) | Category | Description |
|---|---|---|---|
| **1–112** | 112 | Data Transfer Models | Pydantic request models (`RunRequest`, `RollbackRequest`, `ResolveRequest`, `BulkResolveRequest`, `BulkUndoRequest`, `ManualSortRequest`, `SortShowRequest`, `SortGroupRequest`, `SettingsUpdateRequest`). |
| **114–618** | 505 | Folder & Media Intelligence | Helper functions: `format_bytes`, `list_files_in_dir`, `clean_detected_show_name`, `load_poster_cache`, `save_poster_cache`, `fetch_show_poster`, `extract_clean_stem`, `common_prefix_words`, `cluster_unsure_files`, `inspect_downloads_folder`. |
| **620–1505** | 886 | Route Handlers & Orchestration | 27 REST API endpoints inside `create_app`: batch history, execution, rollback, file downloads, quarantine review, manual sorting, library cataloging, settings mutation, process restart, GitHub updater. |
| **1506–4915** | 3,410 | Monolithic HTML/CSS/JS Template | Raw string literal (`html = r"""<!DOCTYPE html>..."""`) served at `GET /` with embedded CSS (14 themes), responsive markup, and extensive client-side JavaScript. |

---

## 3. Existing REST API Contract

The server exposes 27 REST API endpoints. Strict 100% backward compatibility must be preserved across all request signatures, query parameters, and response structures.

| HTTP Method | Route | Request Signature / Payload | Response Schema | Description & Side Effects |
|---|---|---|---|---|
| `GET` | `/api/status` | None | `{ "version": str, "status": "online", "database": str, "dry_run": bool, "confidence_threshold": float, "min_file_age_seconds": int, "scan_interval_seconds": int, "action": str, "downloads_dir": str, "movies_dir": str, "shows_dir": str, "total_batches": int, "pending_quarantine": int }` | Reports system health, active directory paths, config flags, and database statistics. |
| `GET` | `/api/batches` | Query: `limit: int = 20` | `List[{ "id": str, "created_at": str\|null, "completed_at": str\|null, "dry_run": bool, "status": str, "total_files": int, "moved_files": int, "quarantined_files": int, "skipped_files": int, "failed_files": int }]` | Returns recent batch execution records ordered descending by created_at. |
| `GET` | `/api/batches/{batch_id}` | Path: `batch_id: str` | `{ "batch": { "id": str, "status": str, "dry_run": bool, "created_at": str\|null }, "operations": List[{ "id": int, "src": str, "dst": str, "action": str, "status": str, "category": str, "confidence": float, "details": dict }] }` | Returns detailed operation journal for a specific batch; 404 if not found. |
| `POST` | `/api/batches/clear` | None | `{ "status": "cleared", "message": "Activity and batch history successfully cleared" }` | Deletes all `Operation` and `BatchRecord` rows from the database. |
| `POST` | `/api/run` | Body: `RunRequest(dry_run: Optional[bool] = None)` | `{ "batch_id": str, "dry_run": bool, "total_files": int, "moved_files": int, "quarantined_files": int, "skipped_files": int, "failed_files": int, "operations": List[{ "src": str, "dst": str, "action": str, "category": str, "confidence": int (0-100), "quarantine": bool, "quarantine_reason": str\|null }], "errors": List[str] }` | Executes a sorter run (dry-run or live). Moves files, updates database, records batch. |
| `POST` | `/api/rollback` | Body: `RollbackRequest(batch_id: Optional[str] = None)` | `{ "status": "ok", "reverted_files": int }` | Reverts file movements of specified batch ID (or the most recent batch if omitted). |
| `POST` | `/api/rollback/all` | None | `{ "status": "ok", "reverted_files": int }` | Reverts all previously completed batches back to source directories. |
| `GET` | `/api/files` | None | `{ "downloads": { "path": str, "total_files": int, "files": List[dict], "shows": List[dict], "unsure_groups": List[dict], "singles": List[dict] }, "movies": { "path": str, "files": List[dict] }, "shows": { "path": str, "files": List[dict] } }` | Lists directory contents. Excludes all `.txt` and `.srt` files across all folders. |
| `POST` | `/api/files/test-sample` | None | `{ "status": "created", "files": List[str], "directory": str }` | Writes 6 test media files into the downloads folder for testing. |
| `DELETE` | `/api/files/download` | Query: `name: str` | `{ "status": "deleted", "name": str }` | Deletes file from downloads folder. Deletes companion `.txt` if present and prunes empty parent folders. |
| `GET` | `/api/quarantine` | None | `{ "pending": List[{ "id": int, "src": str, "filename": str, "suggested_category": str, "confidence": int (0-100), "reason": str, "signals": dict, "created_at": str\|null, "status": str }], "resolved": List[{ "id": int, "src": str, "filename": str, "category": str, "resolved_path": str, "resolved_filename": str\|null, "resolved_at": str\|null, "status": str }] }` | Lists pending and resolved quarantine items with diagnostic signals. |
| `POST` | `/api/quarantine/{item_id}/resolve` | Path: `item_id: int`<br>Body: `ResolveRequest(category: str, target_path: Optional[str], title: Optional[str], year: Optional[int], season: Optional[int], episode: Optional[int])` | `{ "status": "resolved", "item_id": int, "category": str, "destination": str }` | Resolves a quarantined file, moving it to destination path and marking status RESOLVED. |
| `POST` | `/api/quarantine/bulk-resolve` | Body: `BulkResolveRequest(category: str, item_ids: Optional[List[int]], target_path: Optional[str], title: Optional[str], year: Optional[int], season: Optional[int], episode: Optional[int])` | `{ "status": "ok", "resolved_count": int, "failed_count": int, "errors": List[str] }` | Bulk resolves multiple quarantined items. |
| `POST` | `/api/quarantine/{item_id}/undo` | Path: `item_id: int` | `{ "status": "undone", "item_id": int }` | Undoes quarantine item: if RESOLVED, moves file back to source and marks PENDING; if PENDING, removes record. |
| `POST` | `/api/quarantine/bulk-undo` | Body: `BulkUndoRequest(item_ids: Optional[List[int]], scope: str = "pending")` | `{ "status": "ok", "undone_count": int }` | Bulk undoes pending or resolved quarantine items. |
| `POST` | `/api/files/manual-sort` | Body: `ManualSortRequest(relative_path: str, category: str, title: str, year: Optional[int], season: Optional[int], episode: Optional[int])` | `{ "status": "moved", "destination": str }` | Manually organizes a single file into movie or TV show hierarchy and records item in library catalog. |
| `POST` | `/api/files/sort-show` | Body: `SortShowRequest(show_name: str, target_destination: Optional[str], relative_paths: Optional[List[str]], dry_run: bool = False)` | `{ "status": "ok", "show_name": str, "total_files": int, "moved_files": int, "quarantined_files": int, "failed_files": int, "batch_id": str, "operations": List[dict] }` | Executes a targeted sort pipeline restricted to episodes of a specific TV show. |
| `POST` | `/api/files/sort-group` | Body: `SortGroupRequest(group_name: str, group_type: str = "folder", category: Optional[str] = "tv", title: Optional[str] = None, year: Optional[int] = None, relative_paths: List[str], dry_run: bool = False)` | `{ "status": "ok", "group_name": str, "title": str, "category": str, "total_files": int, "moved_files": int, "quarantined_files": int, "failed_files": int, "batch_id": str, "operations": List[dict] }` | Sorts a clustered group of unsure files (from shared subfolder or prefix) together. |
| `GET` | `/api/library` | Query: `category: Optional[str] = None, search: Optional[str] = None` | `{ "total_shows": int, "total_movies": int, "shows": List[dict], "movies": List[dict] }` | Returns catalog of indexed shows and movies with optional text search and category filtering. |
| `POST` | `/api/library/rescan` | None | `{ "status": "ok", "shows_synced": int, "movies_synced": int, "total_files_indexed": int }` | Rescans movies and shows directories on disk and updates the database library catalog. |
| `GET` | `/api/settings` | None | `{ "downloads_dir": str, "movies_dir": str, "shows_dir": str, "dry_run": bool, "confidence_threshold": float, "min_file_age_seconds": int, "scan_interval_seconds": int, "cleanup_empty_dirs": bool, "rename_files": bool, "movie_template": str, "tv_template": str, "action": str, "server_host": str, "server_port": int }` | Returns active runtime settings. |
| `POST` | `/api/settings` | Body: `SettingsUpdateRequest` (all fields optional) | `{ "status": "saved", "message": "Settings updated and saved to .env" }` | Updates runtime settings, updates `os.environ`, ensures destination directories exist, and rewrites `.env`. |
| `POST` | `/api/restart` | None | `{ "status": "restarting", "message": "Server restart initiated. Reconnecting in a few seconds..." }` | Triggers graceful server process restart via background task (`os.execv` or PM2 exit). |
| `GET` | `/api/poster/local` | Query: `path: str` | `FileResponse` | Serves local cover/poster artwork images securely. Rejects non-image file extensions. |
| `GET` | `/api/poster` | Query: `title: str` | `{ "title": str, "poster_url": str\|null }` | Queries poster cache or TVmaze API for show artwork image URL. |
| `GET` | `/api/check_update` | None | `{ "current_version": str, "latest_version": str, "update_available": bool }` | Queries GitHub API tags to check for available software updates. |
| `POST` | `/api/perform_update` | None | `{ "status": "update_started" }` | Schedules background task running `git pull origin main`. |
| `GET` | `/` | None | `HTMLResponse` | Serves the full single-page web dashboard HTML. |

---

## 4. Single-Page Web Dashboard Architecture

The dashboard is served via `GET /` as an interactive single-page application (SPA).

### 4.1 Client Layout & Tabs

1. **Dashboard & Activity Tab (`#tab-dashboard`)**
   - Summary stat cards: Downloads count, Movies count, Shows count, Active Mode (Live / Dry-run badge).
   - Execution plan container: Shows live operation table during sort runs (src, dst, action, confidence badge, quarantine status).
   - Recent Activity Batches table: Lists historical batches with status badges, file counts, rollback action button, and "Clear Activity History" button.

2. **Folder Explorer Tab (`#tab-files`)**
   - Excludes `.txt` and `.srt` files: Both `list_files_in_dir` and `inspect_downloads_folder` enforce exclusion of files matching `endswith((".txt", ".srt"))`. Subtitles are paired and managed via sidecar routines rather than cluttering the file explorer.
   - Categorized Shows Accordion: Shows discovered episodic series grouped by title. Includes show poster, season summary, file count, "Sort Show Now" button, and expandable episode list.
   - Unsure Groups Section: Lists clustered files that share a common folder or title prefix. Each card provides a "Sort Group as TV" button and "Manual / Custom Sort" modal launcher.
   - Singles Table: Shows standalone files with detected type (`movie` or `other`), predicted destination, "Delete" button, "Sort as Movie" button, and "Manual Sort" modal launcher.

3. **Library Catalog Tab (`#tab-library`)**
   - Shows & Movies badge tallies.
   - "Rescan Disk Library" action button triggering `/api/library/rescan`.
   - Category filtering pills: "All", "Shows", "Movies".
   - Real-time client search input filtering by title or path.
   - Grid cards with poster images, title, year, season/episode counts, and destination paths.

4. **Quarantine Review Tab (`#tab-quarantine`)**
   - Tab switcher for "Pending" and "Resolved" review queues.
   - Pending table displays filename, suggested category, confidence meter, failure reason, and diagnostic signals.
   - Actions: "Resolve as Movie", "Resolve as TV", "Manual Resolve Modal", and "Unflag / Dismiss".
   - Bulk Resolution Bar: Multi-item selection, bulk resolve dropdown, and bulk undo buttons.
   - Resolved table displays original source, resolved target, resolution timestamp, and one-click "Undo" button restoring file to source.

5. **Settings & .env Tab (`#tab-settings`)**
   - Form for modifying all core settings: `downloads_dir`, `movies_dir`, `shows_dir`, `dry_run`, `confidence_threshold`, `min_file_age_seconds`, `scan_interval_seconds`, `cleanup_empty_dirs`, `rename_files`, `movie_template`, `tv_template`, `action`.
   - Theme Selector Dropdown and Grid of Visual Theme Swatches.
   - "Save Settings & Update .env" button.
   - "Restart Media Sorter Server" button.

### 4.2 Theme System (14 Distinct Themes)

The dashboard supports 14 themes defined through CSS custom variables (`--bg`, `--card-bg`, `--border`, `--text`, `--accent`, `--emerald`, `--indigo`, etc.):

1. `cyber-dark` (Default)
2. `oled-neon`
3. `nord-frost`
4. `dracula`
5. `emerald-matrix`
6. `solar-sunset`
7. `tokyo-night`
8. `synthwave`
9. `abyssal-ocean`
10. `monokai-pro`
11. `terminal-crt` (monospaced green CRT glow)
12. `paper-light` (clean light mode)
13. `neo-brutalism` (bold high-contrast borders and yellow accents)
14. `aurora-glass` (frosted glass morphism)

The active theme is persisted in `localStorage.getItem('ms-theme')` and applied immediately to `<html data-theme="...">`.

### 4.3 Classification Modals

1. **Manual Classification Modal (`#modal-manual-sort`)**
   - Supports single-file manual sorting, group sorting, and quarantine resolution.
   - Form fields:
     - Target filename (read-only label)
     - Category dropdown (`movie`, `tv`, `music`, `audiobooks`, `podcasts`, `other`)
     - Title input (with auto-parsed defaults)
     - Year input (for movies)
     - Season and Episode numeric inputs (for TV shows)
     - Target path override input
     - Real-time Destination Preview banner showing calculated destination path
   - Triggers `POST /api/files/manual-sort`, `POST /api/files/sort-group`, or `POST /api/quarantine/{id}/resolve`.

2. **Quick Settings Modal (`#modal-settings`)**
   - Overlay modal allowing instant reconfiguration without leaving the active tab.

---

## 5. Existing Test Suite Baseline

### 5.1 Test Inventory

The existing automated test suite consists of **75 unit and integration tests** located in `/md0/media-sorter/tests`:

```
tests/
├── integration/
│   ├── test_end_to_end.py                       ( 1 test )
│   └── test_messy_filenames_and_fuzz.py         ( 7 tests: 6 parametrized + 1 hypothesis fuzz )
└── unit/
    ├── test_analyzer.py                         ( 5 tests )
    ├── test_classifier.py                       ( 14 tests )
    ├── test_config_and_db.py                    ( 3 tests )
    ├── test_executor_and_rollback.py            ( 7 tests )
    ├── test_library_and_groups.py               ( 4 tests )
    ├── test_namer.py                            ( 6 tests )
    ├── test_quarantine.py                       ( 2 tests )
    ├── test_server_and_env.py                   ( 14 tests )
    └── test_tokenizer.py                        ( 12 tests )
Total: 75 tests
```

### 5.2 Test Environment & Execution

- **Python Interpreter:** Python 3.14.3 (`/md0/media-sorter/.venv/bin/python`)
- **Pytest Version:** pytest 9.1.1
- **Plugins Loaded:** `hypothesis-6.167.1`, `anyio-4.15.0`, `asyncio-1.4.0`
- **Execution Command:**
  ```bash
  /md0/media-sorter/.venv/bin/pytest -v
  ```
- **Execution Result:**
  ```
  ======================== 75 passed, 2 warnings in 1.29s ========================
  ```
- **Pass Rate:** **100% (75/75 passed)**. Zero failures, zero errors.

### 5.3 Filesystem Safety Guardrails in Tests

- All 11 test modules strictly use pytest's `tmp_path: Path` fixture.
- Databases are created on-the-fly as temporary SQLite files (e.g. `tmp_path / "test.db"`).
- Source and destination directories (`downloads`, `movies`, `shows`, `incoming`, `organized`) are isolated within temporary folders.
- **Guardrail Verification:** No tests touch or mutate production media directories (`/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`).

### 5.4 Coverage Infrastructure

- `pytest-cov` is currently **not installed** in the virtual environment.
- To measure test coverage and ensure modules achieve or exceed the 90% threshold specified in R4:
  `coverage` or `pytest-cov` package should be installed or run via Python's built-in coverage tooling (`python -m coverage run -m pytest tests/`).

---

## 6. Architectural Decoupling Roadmap (R1)

To eliminate the monolithic 4,915-line `server.py` while preserving 100% backward compatibility with existing tests and REST API clients:

### 6.1 Proposed Target Architecture

Decompose `src/media_sorter/server.py` into focused, cohesive modules:

```
src/media_sorter/
├── server.py                                  # Backwards-compatible facade re-exporting create_app,
│                                              # inspect_downloads_folder, list_files_in_dir, etc.
├── web/                                       # New web / presentation package
│   ├── __init__.py
│   ├── app.py                                 # create_app factory & lifespan manager
│   ├── schemas.py                             # Pydantic request models (RunRequest, etc.)
│   ├── inspector.py                           # inspect_downloads_folder, list_files_in_dir, clustering
│   ├── posters.py                             # load/save poster cache, fetch_show_poster
│   ├── routes/                                # Decoupled APIRouters
│   │   ├── __init__.py
│   │   ├── status.py                          # /api/status, /api/restart, /api/check_update, /api/perform_update
│   │   ├── batches.py                         # /api/batches, /api/batches/{id}, /api/batches/clear, /api/run, /api/rollback
│   │   ├── files.py                           # /api/files, /api/files/test-sample, /api/files/download, manual-sort, sort-show, sort-group
│   │   ├── quarantine.py                      # /api/quarantine, resolve, undo, bulk-resolve, bulk-undo
│   │   ├── library.py                         # /api/library, /api/library/rescan
│   │   ├── settings.py                        # /api/settings GET & POST
│   │   └── ui.py                              # GET / rendering the dashboard HTML
│   └── templates/
│       └── dashboard.html                     # Clean extracted HTML template
```

### 6.2 Backward Compatibility Requirements

1. Existing tests directly import helpers from `media_sorter.server`:
   - `from media_sorter.server import create_app`
   - `from media_sorter.server import inspect_downloads_folder, list_files_in_dir`
   - `from media_sorter.server import cluster_unsure_files, create_app, inspect_downloads_folder`
   - `src/media_sorter/cli.py` line 307: `from .server import create_app`
   **Requirement:** `src/media_sorter/server.py` must retain top-level re-exports of `create_app`, `inspect_downloads_folder`, `list_files_in_dir`, `cluster_unsure_files`, `clean_detected_show_name`, and `fetch_show_poster`.
2. All 27 REST API endpoints must retain exact URL paths, query arguments, Pydantic body validation schemas, and JSON response keys.
3. The dashboard UI at `GET /` must retain all 14 themes, `.txt`/`.srt` exclusion behaviors, and modal workflows.

---

## 7. Next Step Recommendations for Phase 2

1. **Database Hardening (R2):** Audit `get_db_session` in `src/media_sorter/db.py`. Ensure engine connection pooling handles concurrent requests safely without creating ad-hoc `scoped_session` factories on every invocation.
2. **Modular Route Decoupling (R1):** Extract routes into separate `APIRouter` modules and verify that all 75 tests continue to pass cleanly.
3. **Template Extraction:** Move the 3,400-line inline HTML template into an external template asset or dedicated module while preserving the `__VERSION_PLACEHOLDER__` substitution.
4. **Coverage Baseline Measurement (R4):** Install `coverage` to measure line coverage across core modules and identify edge cases needing expanded unit tests.
