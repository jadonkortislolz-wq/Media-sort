# Project: Media Sorter Hardening & Test Expansion

## Architecture
The Media Sorter is a Python application (FastAPI + SQLAlchemy + SQLite) for automated and manual organization of TV shows, movies, and anime files.
- **Core Engine**: `media_sorter.sorter.MediaSorter`, `media_sorter.scanner.MediaScanner`, `media_sorter.tokenizer.FilenameTokenizer`, `media_sorter.classifier.MediaClassifier`, `media_sorter.namer.MediaNamer`, `media_sorter.executor.FileExecutor`.
- **Database Layer**: SQLite with WAL mode, SQLAlchemy ORM models (`BatchRecord`, `FileRecord`, `QuarantineRecord`, `ConfigAudit`, `OperationLog`, `LibraryItem`), Alembic migrations.
- **Service & Routing Layer**: FastAPI server orchestrating REST API endpoints, background auto-sorting workers, file inspection/clustering, and single-page dashboard.
- **Safety & Isolation**: Filesystem isolation traps, mock fixtures, non-mutating read endpoints, atomic move/rollback operations.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Server Architecture Decoupling & UI Extraction | Extract 3,404-line HTML/CSS/JS dashboard into external templates/UI module, partition 27 endpoints into modular FastAPI router controllers (`routes/`), decouple file inspection into `file_service.py`, preserve backward-compatible facade re-exports in `server.py` | M3 | R1, survey |
| F2 | Web Dashboard & Theme Preservation | Retain full single-page web dashboard functionality: 5 tabs (Dashboard, Folder Explorer with `.txt`/`.srt` exclusions, Library catalog, Quarantine queue, Settings), 14 CSS themes with dropdown & swatches, 2 interactive modals | M3 | R1, survey |
| F3 | REST API Contract & Backward Compatibility | Maintain 100% backward compatibility for all 27 REST endpoints (`/api/status`, `/api/files`, `/api/run`, `/api/rollback`, `/api/library`, `/api/quarantine`, etc.) in request parameters, payloads, and response JSON schemas | M3 | R1, survey |
| F4 | Database Session Lifecycle & Engine Management | Eliminate broken `scoped_session` re-instantiation in `db.py`, provide proper connection pooling, clean session lifecycle scoping (`session.close()`, `remove()`), and thread-safe session factories | M1 | R2, survey |
| F5 | Database Transaction Safety & Concurrency Hardening | Implement concurrency locking on rollback and manual sort operations to prevent race conditions against active background sort runs; fix partial rollback batch state in `executor.py`; fix non-transactional `undo_item()` in `quarantine.py`; offload synchronous `sorter.run()` from async event loop in `auto_sort_worker` | M1 | R2, survey |
| F6 | Schema Synchronization & Library Catalog Integrity | Add missing `library_items` table to Alembic migrations; fix silent `AttributeError` on `op.status` in `sorter.py:271` so live sorts update `LibraryItem` entries; remove read-endpoint mutation in `GET /api/files` that cumulatively inflates `item_count` | M1 | R2, survey |
| F7 | Tokenizer Edge-Case Expansion | Enhance `FilenameTokenizer` regexes and parsing to handle Roman numerals (`Season II Episode IV`), ambiguous years (`1917`, `2001`, `2049`), anime titles with parentheses (`Fairy Tail (2014)`), and multi-part episode formats (`01-02`, `1x01-02`, `S01E01E02E03`) | M2 | R3, R4, survey |
| F8 | Error Handling, Input Validation & Security Guardrails | Sanitize user-provided filename strings in `/api/files/manual-sort`; validate storage boundaries in `/api/poster/local` to prevent arbitrary file reading; implement defensive structured error responses across all endpoints | M2 | R3, survey |
| F9 | Companion File Handling, Pairing, Exclusions & Cleanup | Verify and harden sidecar pairing (`.srt`, `.ass`, `.nfo`, etc.), language suffix preservation (`.en.srt`), Folder Explorer `.txt`/`.srt` exclusions, and directory cleanup routines | M2 | R1, R3, survey |
| F10 | Filesystem Safety Guardrails & Environment Isolation | Add root `tests/conftest.py` with autouse safety trap protecting production directories (`/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`); decouple `Settings` from process-wide `os.environ` mutation in `POST /api/settings` to prevent cross-test contamination | M1 | R5, survey |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Requirement-driven opaque-box test suite (Tiers 1-4, ≥115 test cases), test runner, and `TEST_READY.md` publishing | None | PLANNED |
| M1 | Filesystem Safety Guardrails & Database Reliability Hardening | F4 (Session lifecycle), F5 (Transaction safety & concurrency), F6 (Schema sync & catalog updates), F10 (Filesystem safety trap in `tests/conftest.py` & env isolation) | None | PLANNED |
| M2 | Tokenizer Edge-Case Expansion & Input Validation Hardening | F7 (Roman numerals, ambiguous years, anime parentheses, multi-episodes), F8 (Input sanitization & security), F9 (Companion file pairing & exclusions) | M1 | PLANNED |
| M3 | Server Architectural Decoupling & UI Template Extraction | F1 (Monolith decomposition into modular routers and file service), F2 (Dashboard UI & theme preservation), F3 (REST API contract backward compatibility) | M1, M2 | PLANNED |
| M4 | Final Milestone: Full E2E Verification & Adversarial Coverage Hardening | Phase 1: Pass 100% of E2E test suite (Tiers 1-4) + 75 baseline tests. Phase 2: Adversarial Coverage Hardening (Tier 5) with Challenger loop to verify ≥90% coverage on core modules | E2E, M1, M2, M3 | PLANNED |

## Code Layout
- `src/media_sorter/`
  - `config.py`: Configuration models and settings
  - `models.py`: SQLAlchemy ORM models
  - `db.py`: Database engine and session factory
  - `scanner.py`: File scanning and sidecar pairing
  - `tokenizer.py`: Filename tokenization and regex parsing
  - `classifier.py`: Media categorization heuristics
  - `namer.py`: Standardized filename generation
  - `executor.py`: File moving, copying, and rollback execution
  - `sorter.py`: High-level sorting orchestrator
  - `library.py`: Media library catalog management
  - `quarantine.py`: Quarantine management
  - `file_service.py`: Decoupled file inspection and clustering service (extracted from server.py)
  - `templates/`: Extracted single-page web dashboard HTML/CSS/JS template
  - `routes/`: Modular FastAPI route controllers
    - `status.py`, `batches.py`, `files.py`, `quarantine.py`, `library.py`, `settings.py`, `posters.py`
  - `server.py`: Backward-compatible facade re-exporting `create_app` and core helpers
  - `cli.py`: CLI command-line interface
- `tests/`
  - `conftest.py`: Root safety guardrails, env sanitization, and filesystem protection traps
  - `unit/`: Unit tests for core components
  - `integration/`: Integration tests for server and pipeline workflows
  - `e2e/`: Opaque-box requirement-driven E2E test suite (Tiers 1-4)
- `alembic/`: Database migrations

## Interface Contracts
### `server.py` Facade ↔ External Callers & Tests
- `create_app(settings: Optional[Settings] = None, engine: Optional[Engine] = None) -> FastAPI`
- `inspect_downloads_folder(downloads_dir: Path, movies_dir: Path, shows_dir: Path, ...) -> Dict[str, Any]`
- `list_files_in_dir(path: Path) -> List[Dict[str, Any]]`
- `cluster_unsure_files(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]`
- `clean_detected_show_name(name: str) -> str`
- Request models: `RunRequest`, `RollbackRequest`, `ResolveRequest`, `BulkResolveRequest`, `BulkUndoRequest`, `ManualSortRequest`, `SortShowRequest`, `SortGroupRequest`, `SettingsUpdateRequest`.

### `db.py` ↔ Sorter & Routes
- `get_engine(database_url: str) -> Engine`
- `get_session_factory(engine: Engine) -> sessionmaker[Session]`
- `get_db_session(engine: Engine) -> Generator[Session, None, None]` (proper context manager with clean commit/rollback/close)

### `tokenizer.py` ↔ Scanner & Classifier
- `FilenameTokenizer.tokenize(path: Path) -> TokenizedMedia`
- Supports Roman numerals (`I..XX`), ambiguous years without title loss, anime titles with parentheses, and multi-part episodes (`multi_episodes: List[int]`).
