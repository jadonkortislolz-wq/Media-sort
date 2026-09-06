# Handoff Report: REST API Endpoints, UI Operations, and Backward Compatibility Survey

## 1. Observation

### 1.1 Test Suite Status and Environment
Command: `/md0/media-sorter/.venv/bin/pytest tests/`
Output:
```
======================== 75 passed, 2 warnings in 1.42s ========================
```
Existing unit and integration test suite covers 75 tests spanning `test_analyzer.py`, `test_classifier.py`, `test_config_and_db.py`, `test_executor_and_rollback.py`, `test_library_and_groups.py`, `test_namer.py`, `test_quarantine.py`, `test_server_and_env.py`, `test_tokenizer.py`, `test_end_to_end.py`, and `test_messy_filenames_and_fuzz.py`.

### 1.2 Monolithic Architecture & Route Layout
File: `src/media_sorter/server.py` (5,293 lines, 224,040 bytes)
- Lines 1–1525: FastAPI application setup, Pydantic models, helper functions (`format_bytes`, `list_files_in_dir`, `clean_detected_show_name`, `cluster_unsure_files`, `inspect_downloads_folder`), lifespan background tasks, and all 27 REST API endpoints.
- Lines 1526–5292: Monolithic inline single-page Web Dashboard (`render_dashboard()`) returning inline HTML, CSS (14+ themes), and 3,000+ lines of vanilla JavaScript making asynchronous `fetch()` calls to `/api/*`.
- Notice: The `src/media_sorter/routes/` directory planned in `PROJECT.md` does not yet exist. All endpoint route definitions currently reside in `server.py:create_app()`.

### 1.3 Target Endpoints & Payload Contracts
Direct inspection of route handlers in `src/media_sorter/server.py`:

#### 1. File Scanning & Inspection (`GET /api/files` vs `/api/files/scan`)
- `server.py:803-820`:
  ```python
  @app.get("/api/files")
  def get_files():
      downloads_path = settings.get_source_paths()[0] if settings.get_source_paths() else Path("downloads")
      movies_path = settings.get_destination_path("movie")
      shows_path = settings.get_destination_path("tv")
      return {
          "downloads": inspect_downloads_folder(downloads_path, settings, engine=engine),
          "movies": {"path": str(movies_path), "files": list_files_in_dir(movies_path)},
          "shows": {"path": str(shows_path), "files": list_files_in_dir(shows_path)},
      }
  ```
- **Crucial Observation**: Route `/api/files/scan` is referenced in `ORIGINAL_REQUEST.md:62` ("Ensure existing UI operations and server API endpoints (`/api/files/scan`, `/api/files/sort-show`, `/api/library`) continue functioning seamlessly"), but does **NOT** exist as a route in `server.py`. The active endpoint is `GET /api/files`. Any external client calling `/api/files/scan` currently receives a `404 Not Found`.
- Output of `inspect_downloads_folder(directory, settings, engine)` (`server.py:408-617`):
  ```python
  {
      "path": str(directory),
      "total_files": len(all_files),      # int
      "files": all_files,                  # List[FileInfo]
      "shows": shows_list,                # List[ShowInfo]
      "unsure_groups": unsure_groups,      # List[GroupInfo]
      "singles": singles,                  # List[FileInfo]
  }
  ```
  - `FileInfo` schema:
    `name` (str), `relative_path` (str), `size` (str, e.g. "1.2 GB"), `size_bytes` (int), `modified` (str, "%Y-%m-%d %H:%M:%S"), `season` (Optional[int]), `episode` (Optional[int]), `episode_title` (Optional[str]), `is_show` (bool), `believed_show` (Optional[str]), and for unsure files: `detected_type` (str: "movie" | "other"), `believed_title` (str), `believed_destination` (Optional[str]).
  - `ShowInfo` schema:
    `show_name` (str), `count` (int), `seasons` (List[int]), `season_summary` (str, e.g. "Season 01, Season 02"), `believed_destination_folder` (str), `poster_url` (Optional[str]), `files` (List[FileInfo]).
  - `GroupInfo` schema:
    `group_id` (str), `group_name` (str), `group_type` (str: "folder" | "name"), `folder_name` (Optional[str]), `suggested_title` (str), `believed_destination_folder` (str), `count` (int), `files` (List[FileInfo]).

#### 2. Show Organization (`POST /api/files/sort-show`)
- `server.py:82-87` (Request Model):
  ```python
  class SortShowRequest(BaseModel):
      show_name: str
      target_destination: Optional[str] = None
      relative_paths: Optional[List[str]] = None
      dry_run: bool = False
  ```
- `server.py:1173-1241` (Handler):
  - Resolves target files either from `req.relative_paths` or by finding matching show in `inspect_downloads_folder`. Raises 404 if no files match.
  - Calls `sorter.run(dry_run=req.dry_run, filter_paths=resolved_files, show_name_override=req.show_name)`.
  - In `sorter.py:228-236`, `show_name_override` forces `cls_res.category = "tv"`, `cls_res.tokens.title = show_name_override`, `cls_res.tokens.is_episodic = True`, `cls_res.needs_quarantine = False`, and `cls_res.confidence = max(cls_res.confidence, 0.95)`.
  - In `server.py:1213-1220`, records detected show in library:
    `record_detected_item(session, settings, req.show_name, "tv", destination_folder=str(shows_base / req.show_name), delta_count=report.moved_files)`.
  - Response Schema:
    ```python
    {
        "status": "ok",
        "show_name": req.show_name,          # str
        "total_files": report.total_files,    # int
        "moved_files": report.moved_files,    # int
        "quarantined_files": report.quarantined_files, # int
        "failed_files": report.failed_files,  # int
        "batch_id": report.batch_id,          # str (UUID)
        "operations": [                       # List[Dict]
            {
                "src": str(op.src.name),      # str (filename only)
                "dst": str(op.dst),           # str (full destination path)
                "category": op.category,      # str ("tv")
                "confidence": int(op.confidence * 100), # int percentage (e.g. 95)
            }
        ]
    }
    ```

#### 3. Unsure Group Sorting (`POST /api/files/sort-group`)
- `server.py:89-97` (Request Model):
  ```python
  class SortGroupRequest(BaseModel):
      group_name: str
      group_type: str = "folder"
      category: Optional[str] = "tv"
      title: Optional[str] = None
      year: Optional[int] = None
      relative_paths: List[str]
      dry_run: bool = False
  ```
- `server.py:1243-1345`:
  - When `category == "tv"`, delegates to `sorter.run(filter_paths=resolved_files, show_name_override=target_title)`.
  - When `category == "movie"`, formats folder as `f"{target_title} ({req.year})"` or `target_title`, moves files, and records to library with `category="movie"`.

#### 4. Manual Single File Sorting (`POST /api/files/manual-sort`)
- `server.py:73-80` (Request Model):
  ```python
  class ManualSortRequest(BaseModel):
      relative_path: str
      category: str
      title: str
      year: Optional[int] = None
      season: Optional[int] = None
      episode: Optional[int] = None
  ```
- `server.py:1114-1171`:
  - If `category == "movie"`: creates folder `f"{movie_title} ({year})"`, file `f"{folder_name}{ext}"`.
  - If `category == "tv"`: creates `shows_base / show_name / f"Season {season:02d}" / f"{show_name} - S{season:02d}E{episode:02d}{ext}"`.
  - Moves file and updates library item.
  - Response: `{"status": "moved", "destination": str(final_dst)}`.

#### 5. Pipeline Execution (`POST /api/run`)
- `server.py:40-42` (Request Model):
  ```python
  class RunRequest(BaseModel):
      dry_run: Optional[bool] = None
  ```
- `server.py:759-786`:
  - Executes `sorter.run(dry_run=is_dry)`.
  - Response schema includes: `batch_id`, `dry_run`, `total_files`, `moved_files`, `quarantined_files`, `skipped_files`, `failed_files`, `operations` (list with `src`, `dst`, `action`, `category`, `confidence`, `quarantine`, `quarantine_reason`), and `errors`.

#### 6. Library Catalog (`GET /api/library`)
- `server.py:1347-1352`:
  - Query parameters: `category: Optional[str] = None`, `search: Optional[str] = None`.
  - Calls `list_library_items(session, category=category, search=search)` in `src/media_sorter/library.py:245-290`.
  - Response schema:
    ```json
    {
      "total_shows": 12,
      "total_movies": 5,
      "shows": [
        {
          "id": 1,
          "title": "Breaking Bad",
          "category": "tv",
          "year": null,
          "destination_folder": "/md0/shows/Breaking Bad",
          "poster_url": null,
          "item_count": 62,
          "seasons_count": 5,
          "first_detected": "2026-09-05T18:00:00+00:00",
          "last_updated": "2026-09-05T18:00:00+00:00"
        }
      ],
      "movies": [
        {
          "id": 2,
          "title": "Inception",
          "category": "movie",
          "year": 2010,
          "destination_folder": "/md0/movies/Inception (2010)",
          "poster_url": null,
          "item_count": 1,
          "seasons_count": 0,
          "first_detected": "2026-09-05T18:00:00+00:00",
          "last_updated": "2026-09-05T18:00:00+00:00"
        }
      ]
    }
    ```

#### 7. Library Disk Rescan (`POST /api/library/rescan`)
- `server.py:1354-1361`:
  - Calls `sync_library_from_disk(session, settings)` (`src/media_sorter/library.py:40-154`).
  - Scans `SHOWS_DIR` and `MOVIES_DIR`, detecting folders, counting episodes, counting seasons (`Season \d+` regex), extracting release years (`r"\b(19\d\d|20\d\d)\b"`), and updating `LibraryItem` records in SQLite.
  - Response: `{"status": "ok", "shows_synced": int, "movies_synced": int}`.

### 1.4 Code Locations Where Tokenizer, Classifier, and Namer Are Invoked
| Module | File & Line | Invocation Pattern | Semantic Purpose |
|---|---|---|---|
| `FilenameTokenizer` | `server.py:417` | `tok = FilenameTokenizer()` | Initialized for downloads folder inspection |
| `FilenameTokenizer` | `server.py:459` | `t = tok.tokenize(p)` | Extracts `year`, `title`, `is_episodic`, `is_anime`, `season`, `episode`, `episode_title` per download file |
| `FilenameTokenizer` | `server.py:466` | `part_tok = tok.tokenize(Path(part + p.suffix))` | Tokenizes parent folder components to detect release year if file stem lacks it |
| `FilenameTokenizer` | `server.py:972` | `tok = FilenameTokenizer(); t = tok.tokenize(src_path)` | Resolves quarantine items as movie when title/year are omitted |
| `FilenameTokenizer` | `server.py:996` | `tok = FilenameTokenizer(); t = tok.tokenize(src_path)` | Resolves quarantine items as TV when title/season/episode are omitted |
| `FilenameTokenizer` | `sorter.py:46, 120` | `tokens = self.tokenizer.tokenize(scanned.path)` | Main sorting pipeline tokenization in parallel worker pool |
| `MediaClassifier` | `sorter.py:57, 122` | `classification = self.classifier.classify(scanned, tokens, meta)` | Multi-signal classification based on tokens, container, MIME, duration |
| `MediaNamer` | `sorter.py:61, 169` | `dst = self.namer.generate_destination_path(cls_res)` | Primary media destination path generation using templates |
| `MediaNamer` | `sorter.py:193` | `dst = self.namer.generate_destination_path(cls_res, primary_dst_path=primary_dst)` | Sidecar destination path generation paired with primary media file |

### 1.5 Critical Database Schema Constraints (`models.py`)
File: `src/media_sorter/models.py`
- Table `library_items` (`models.py:162-184`):
  - Columns: `id` (int PK), `title` (str 256), `category` (str 32), `year` (int nullable), `destination_folder` (str 1024), `poster_url` (str 1024 nullable), `item_count` (int), `seasons_count` (int), `first_detected` (DateTime), `last_updated` (DateTime), `extra_info` (JSON nullable).
  - Table constraint: `UniqueConstraint("title", "category", name="uq_library_title_category")`.
  - In `library.py:168`: `if category not in ("tv", "movie"): category = "tv"`.
- Table `operations` (`models.py:95-124`):
  - Columns: `id`, `batch_id`, `src`, `dst`, `action`, `status`, `category` (str 32), `confidence` (float), `src_hash`, `dst_hash`, `details` (JSON), `error_message`, `created_at`, `completed_at`.
- Table `quarantine` (`models.py:126-146`):
  - Columns: `id`, `src` (str unique), `suggested_category` (str 32), `confidence`, `reason`, `signals` (JSON), `status`, `resolved_path`, `created_at`, `resolved_at`.

### 1.6 Latent Defects Discovered in Existing Codebase
1. **NameError in `/api/explorer/set-destination` (`server.py:1453`)**:
   `if 0 <= show_idx < len(currentExplorerShows): currentExplorerShows[show_idx]["believed_destination_folder"] = destination`
   In Python scope, `currentExplorerShows` is never defined (it only exists in frontend JavaScript at `server.py:3924`). Invoking this endpoint from a Python client or test causes a runtime `NameError: name 'currentExplorerShows' is not defined`.
2. **Cumulative Item Count Inflation in `inspect_downloads_folder` (`server.py:581, 600`)**:
   During `inspect_downloads_folder()`, `record_detected_item(..., delta_count=show_item["count"])` is called. In `library.py:186`, `item.item_count = max(0, item.item_count + delta_count)`. Every `GET /api/files` call cumulatively inflates the show's `item_count` in the database without any files actually being moved.
3. **Typo / Class Name Discrepancy (`TokenizedFilename` vs `TokenizedMedia`)**:
   `src/media_sorter/tokenizer.py` defines `@dataclass class TokenizedFilename`, while `PROJECT.md:74` and prompt specifications reference `TokenizedMedia`.

---

## 2. Logic Chain

### 2.1 Preserving UI and REST Contract Backward Compatibility
1. **Observation 1.3.1**: The frontend dashboard JavaScript and existing unit tests (`test_server_and_env.py:63, 193, 236, 421`) make `GET /api/files` requests expecting a response JSON containing `{ "downloads": {...}, "movies": {...}, "shows": {...} }`.
2. **Observation 1.3.1**: Prompt R3 and `ORIGINAL_REQUEST.md:62` mention `/api/files/scan`. If `/api/files/scan` was introduced as a new endpoint name or anticipated endpoint, replacing `/api/files` with `/api/files/scan` would immediately break `dashboard.html` line 4581 (`fetch('/api/files')`) and all existing tests in `test_server_and_env.py`.
3. **Deduction**: The server must retain `GET /api/files` with its exact current signature and response structure, while simultaneously exposing `GET /api/files/scan` (and `POST /api/files/scan`) as an alias route returning the identical file inspection structure (or `downloads` data). This guarantees 100% backward compatibility for both existing code and any new callers.

### 2.2 Impact of Enhancing `tokenizer.py` on Downstream Routes
1. **Observation 1.4**: `server.py:inspect_downloads_folder` relies directly on the attributes of the object returned by `tok.tokenize(p)`:
   - `t.year`: must remain `Optional[int]` (used in `if movie_year: ...`)
   - `t.title`: must remain `Optional[str]`
   - `t.is_episodic`: must remain `bool`
   - `t.is_anime`: must remain `bool`
   - `t.season`: must remain `Optional[int]` (used in `f"Season {season:02d}"` and integer set operations `seasons = sorted(list({f["season"] ...}))`)
   - `t.episode`: must remain `Optional[int]`
   - `t.episode_title`: must remain `Optional[str]`
2. **Observation 1.5 & 1.6.3**: `TokenizedFilename` is currently imported directly by `sorter.py`, `classifier.py`, `test_tokenizer.py`, `test_classifier.py`, and `test_namer.py`.
3. **Deduction**:
   - If `TokenizedFilename` is renamed to `TokenizedMedia` to satisfy `PROJECT.md`, it **MUST** be done via type aliasing (`TokenizedMedia = TokenizedFilename` or `TokenizedFilename = TokenizedMedia`) so neither name causes an `ImportError`.
   - New tokenizer features (Roman numerals `Season II Episode IV`, ambiguous release years `1917`, `2001`, multi-part episodes `01-02` / `multi_episodes: List[int]`) must populate existing scalar attributes (`season`, `episode`) as primary values (e.g. `season=2`, `episode=4`, `multi_episodes=[1, 2]`) while populating new collection fields for extended detail. If `season` or `episode` were changed to strings or lists, integer formatting (`f"Season {season:02d}"`) across `server.py:491, 557, 993, 1001, 1147` and `namer.py:166` would raise `TypeError: %d format: a real number is required, not list/str`.

### 2.3 Impact of `classifier.py` and `namer.py` Modifications
1. **Observation 1.3.2 & 1.3.4**: When sorting TV shows via `POST /api/files/sort-show` or manual sort, destination directories are constructed using `settings.get_destination_path("tv") / show_name / f"Season {season:02d}"`.
2. **Observation 1.5**: `LibraryItem.category` is constrained by SQLite schema and `library.py:168` to `"tv"` and `"movie"`. The UI only contains filters and cards for TV and Movies.
3. **Deduction**:
   - If `classifier.py` classifies Anime as `category="anime"`, the sorter and library integration must route Anime destination storage through `settings.get_destination_path("anime")` (which defaults to `SHOWS_DIR` if `ANIME_DIR` is unset in `config.py:370`).
   - When registering Anime items in `LibraryItem`, `category` must be mapped to `"tv"` (as currently done in `library.py:168-169`) or the database schema must be cleanly migrated via Alembic before introducing a new category string, to prevent breaking the `("title", "category")` unique constraint and UI catalog queries.

### 2.4 Modular Route Decoupling Safety (`PROJECT.md: F1`)
1. **Observation 1.2**: `server.py` is currently a 224 KB monolith containing both backend routes and frontend templates.
2. **Observation 1.1**: Tests in `tests/unit/test_server_and_env.py` import `create_app`, `inspect_downloads_folder`, `list_files_in_dir`, and Pydantic models directly from `media_sorter.server`.
3. **Deduction**: When partitioning endpoints into `src/media_sorter/routes/files.py`, `library.py`, `status.py`, `batches.py`, etc., `server.py` must re-export every function, model, and helper to maintain 100% backward compatibility for existing imports across the entire test suite and external scripts.

---

## 3. Caveats
1. **Database Schema Alteration**: `LibraryItem` currently lacks a dedicated `"anime"` category. Expanding `LibraryItem.category` to include `"anime"` natively would require an Alembic schema migration and updating UI catalog tabs (`dashboard.html`). In the current design, anime is cataloged under `"tv"`, which functions seamlessly.
2. **Read-Endpoint Mutation**: `inspect_downloads_folder()` currently calls `record_detected_item(..., delta_count=show_item["count"])`. Fixing this bug to stop inflating `item_count` during reads will change `item_count` behavior to only increment during live moves. Tests should be verified to confirm no existing test expects read operations to mutate `item_count`.
3. **Frontend In-Memory State**: `POST /api/explorer/set-destination` has an in-memory bug in Python (`currentExplorerShows`), though the frontend JS manages its own local copy. Fixing the Python endpoint to gracefully accept and acknowledge `set-destination` requests without error will improve robustness.

---

## 4. Conclusion
1. **Route Signatures & Schemas**: All 27 existing REST API endpoints, request models, and response structures have been fully cataloged. `GET /api/files` must remain untouched, and an alias `GET /api/files/scan` (and `POST /api/files/scan`) should be provided to satisfy external callers expecting R3's `/api/files/scan` endpoint.
2. **Data Structure Continuity**: `TokenizedFilename` must be aliased to `TokenizedMedia` (`TokenizedMedia = TokenizedFilename`). Scalar fields (`title`, `year`, `season`, `episode`, `is_episodic`, `is_anime`) must preserve their existing primitive types (`Optional[int]`, `Optional[str]`, `bool`) to prevent `TypeError` exceptions in path formatting and UI aggregation.
3. **Series & Show Grouping**: `/api/files/sort-show` and `/api/files/sort-group` rely on `show_name_override` in `sorter.run()`, which sets `category = "tv"`. New anime and multi-part parsing features will cleanly integrate with this flow as long as `show_name` normalization and season numbers are preserved.
4. **Decoupling Strategy**: Route handlers can be safely decoupled from `server.py` into `src/media_sorter/routes/` as long as `server.py` acts as a facade re-exporting all endpoints, helpers, and Pydantic request models.

---

## 5. Verification Method

### 5.1 Baseline Test Verification
Execute the existing 75-test automated test suite:
```bash
/md0/media-sorter/.venv/bin/pytest tests/
```
Expected result: 75 passed, 0 failed.

### 5.2 Endpoint Contract & Regression Tests
Verify specific test suites touching the surveyed endpoints:
```bash
/md0/media-sorter/.venv/bin/pytest tests/unit/test_server_and_env.py tests/unit/test_library_and_groups.py -v
```
Expected assertions to verify:
- `test_web_status_and_dashboard`: checks `/api/status` and `/` dashboard rendering.
- `test_web_sample_generation_and_sorting`: checks `/api/files`, `/api/run`, `/api/rollback`, and `/api/files/download`.
- `test_folder_explorer_excludes_txt_files` & `test_folder_explorer_excludes_srt_files`: verifies exclusions in `GET /api/files`.
- `test_manual_sort_file_api`: verifies `POST /api/files/manual-sort` for both movies and TV shows.
- `test_sort_show_endpoint_and_rollback`: verifies `POST /api/files/sort-show` and subsequent rollback.
- `test_library_sync_and_show_memory`: verifies `POST /api/library/rescan`, `GET /api/library`, and known show matching.
- `test_library_and_sort_group_api`: verifies `POST /api/files/sort-group` and library synchronization.

### 5.3 Invalidation Conditions
The analysis and proposed backward compatibility guarantees are invalidated if:
1. `TokenizedFilename` is renamed without keeping `TokenizedFilename` as an alias, breaking imports in existing modules.
2. `t.season` or `t.episode` in `TokenizedFilename` is changed from `Optional[int]` to a collection/string type, breaking `%02d` formatting.
3. `GET /api/files` response JSON top-level keys (`downloads`, `movies`, `shows`) or `downloads` keys (`path`, `total_files`, `files`, `shows`, `unsure_groups`, `singles`) are modified or renamed.
4. The database schema for `library_items` is modified without a corresponding Alembic migration.
