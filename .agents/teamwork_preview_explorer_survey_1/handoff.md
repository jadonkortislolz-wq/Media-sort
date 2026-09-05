# Handoff Report — Explorer 1 (Codebase Architecture, Server Monolith & Test Baseline)

## 1. Observation

1. **Repository Layout and Monolith Size:**
   - Command `wc -l src/media_sorter/*.py` shows total package code of 9,532 lines.
   - Exact line count for `src/media_sorter/server.py` is **4,915 lines** (51.5% of the total codebase).
   - In `src/media_sorter/server.py`:
     - Lines 40–112 define 9 Pydantic request models (`RunRequest`, `RollbackRequest`, `ResolveRequest`, `BulkResolveRequest`, `BulkUndoRequest`, `ManualSortRequest`, `SortShowRequest`, `SortGroupRequest`, `SettingsUpdateRequest`).
     - Lines 114–618 define formatting helpers, poster cache management, TVmaze external queries, string token cleaning (`clean_detected_show_name`), clustering algorithms (`cluster_unsure_files`), and folder inspection (`inspect_downloads_folder`).
     - Lines 620–1505 define `create_app` containing 27 REST API endpoints and background tasks (`auto_sort_worker`, `initial_library_sync`, `_deferred_restart`, `git_pull`).
     - Lines 1509–4912 contain a 3,404-line monolithic string literal (`html = r"""<!DOCTYPE html>..."""`) serving the single-page web dashboard with 14 CSS themes, interactive modals, and client-side JavaScript.
2. **REST API Contract:**
   - 27 REST endpoints identified in `src/media_sorter/server.py`:
     - System & Status: `GET /api/status`, `GET /api/check_update`, `POST /api/perform_update`, `POST /api/restart`
     - Batches & Execution: `GET /api/batches`, `GET /api/batches/{batch_id}`, `POST /api/batches/clear`, `POST /api/run`, `POST /api/rollback`, `POST /api/rollback/all`
     - Files & Organization: `GET /api/files`, `POST /api/files/test-sample`, `DELETE /api/files/download`, `POST /api/files/manual-sort`, `POST /api/files/sort-show`, `POST /api/files/sort-group`
     - Quarantine Review: `GET /api/quarantine`, `POST /api/quarantine/{item_id}/resolve`, `POST /api/quarantine/bulk-resolve`, `POST /api/quarantine/{item_id}/undo`, `POST /api/quarantine/bulk-undo`
     - Library Catalog: `GET /api/library`, `POST /api/library/rescan`
     - Configuration: `GET /api/settings`, `POST /api/settings`
     - Media Artwork: `GET /api/poster/local`, `GET /api/poster`
     - Dashboard Web UI: `GET /`
3. **Web Dashboard Capabilities & Exclusions:**
   - In `src/media_sorter/server.py` line 129 (`list_files_in_dir`) and line 453 (`inspect_downloads_folder`), files ending in `.txt` or `.srt` are explicitly skipped:
     `if f.lower().endswith((".txt", ".srt")): continue`
   - Tested explicitly in `tests/unit/test_server_and_env.py` lines 160–246 (`test_folder_explorer_excludes_txt_files` and `test_folder_explorer_excludes_srt_files`).
   - 14 distinct themes defined in embedded CSS: `cyber-dark`, `oled-neon`, `nord-frost`, `dracula`, `emerald-matrix`, `solar-sunset`, `tokyo-night`, `synthwave`, `abyssal-ocean`, `monokai-pro`, `terminal-crt`, `paper-light`, `neo-brutalism`, `aurora-glass`.
   - Modals present: `#modal-manual-sort` (manual categorization & destination preview) and `#modal-settings` (quick config).
4. **Test Suite Baseline:**
   - Test framework: `pytest 9.1.1` in `/md0/media-sorter/.venv/bin/pytest`.
   - Command `/md0/media-sorter/.venv/bin/pytest -v` runs **75 tests across 11 test files** (2 integration files with 8 tests, 9 unit files with 67 tests).
   - Execution output: `75 passed, 2 warnings in 1.29s` (100% pass rate).
   - All tests use temporary filesystem fixtures (`tmp_path`) and isolated SQLite databases. No tests access `/md0/jdownloads`, `/md0/movies1`, or `/md0/tv1`.
   - `pytest-cov` is not installed in the virtual environment.

## 2. Logic Chain

1. From Observation 1, `src/media_sorter/server.py` couples presentation (HTML/CSS/JS), API routing, background worker lifecycles, and file analysis algorithms into a single file. Decomposing this file is essential to satisfy Requirement R1 (Architectural Decoupling).
2. From Observation 2, existing callers (CLI `src/media_sorter/cli.py` line 307) and tests (`tests/unit/test_server_and_env.py` line 6, `tests/unit/test_library_and_groups.py` line 14) import directly from `media_sorter.server`. Therefore, the refactored architecture must preserve a backward-compatible facade in `server.py` that re-exports `create_app`, `inspect_downloads_folder`, `list_files_in_dir`, and `cluster_unsure_files`.
3. From Observation 2 and 3, all 27 REST endpoints and dashboard tabs/themes must maintain their signatures and response models to prevent breaking the web interface and existing integration tests.
4. From Observation 4, the test suite currently executes 75 tests with a 100% pass rate in 1.29s. This establishes the exact regression baseline. Any architectural change during Phase 2 must maintain 75/75 passes.
5. To verify the 90% test coverage target required in R4, `coverage` or `pytest-cov` must be integrated into the test environment.

## 3. Caveats

- **Network-dependent providers:** TMDB provider (`src/media_sorter/providers.py`) requires network access and an API key. In the baseline test suite, online metadata is mocked or tested without network calls.
- **TVmaze artwork:** In `fetch_show_poster`, external HTTP requests to `api.tvmaze.com` have a timeout of 2.5s and catch all exceptions. When running unit tests, `allow_network=False` is passed or calls fall back gracefully.
- **Coverage Tooling:** Coverage metrics cannot be gathered until `coverage` or `pytest-cov` is installed in `.venv`.

## 4. Conclusion

The application is fully operational with a robust 75-test baseline that passes 100%. The primary architectural bottleneck is the server monolith (`src/media_sorter/server.py`, 4,915 lines), which combines router endpoints, business logic, file inspection, and an embedded 3,404-line HTML/CSS/JS dashboard.

The recommended decomposition plan for Phase 2:
1. Extract the HTML dashboard to a template file or dedicated UI module.
2. Partition the 27 endpoints into modular FastAPI `APIRouter` controllers (`routes/status.py`, `routes/batches.py`, `routes/files.py`, `routes/quarantine.py`, `routes/library.py`, `routes/settings.py`).
3. Decouple inspection and clustering helpers into a separate service module (`inspector.py` / `file_service.py`).
4. Re-export all public functions from `server.py` to maintain 100% backward compatibility with existing tests and CLI.
5. Add `coverage` to test infrastructure to measure baseline coverage across all core modules.

## 5. Verification Method

- **Test Suite Verification:**
  ```bash
  /md0/media-sorter/.venv/bin/pytest -v
  ```
  Expected: `75 passed` with 0 failures.
- **Inspection of Detailed Survey Report:**
  Examine `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_1/report.md`.
- **Invalidation Conditions:**
  - Any failure in the 75 baseline tests.
  - Missing any of the 27 REST endpoints or broken request/response schemas.
  - Loss of Folder Explorer `.txt`/`.srt` exclusion logic.
  - Breakage of any of the 14 UI themes or classification modals.
