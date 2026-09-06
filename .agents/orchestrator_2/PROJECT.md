# Project: Media Sorter Pattern Matching, Classification & Isolated Benchmark Suite

## Architecture
The Media Sorter is a Python application (FastAPI + SQLAlchemy + SQLite) for automated and manual organization of TV shows, movies, and anime files.
- **Core Engine**: `media_sorter.sorter.MediaSorter`, `media_sorter.scanner.MediaScanner`, `media_sorter.tokenizer.FilenameTokenizer`, `media_sorter.classifier.MediaClassifier`, `media_sorter.namer.MediaNamer`, `media_sorter.executor.FileExecutor`.
- **Database Layer**: SQLite with WAL mode, SQLAlchemy ORM models (`BatchRecord`, `FileRecord`, `QuarantineRecord`, `ConfigAudit`, `OperationLog`, `LibraryItem`), Alembic migrations.
- **Service & Routing Layer**: FastAPI server orchestrating REST API endpoints, background auto-sorting workers, file inspection/clustering, and single-page dashboard.
- **Safety & Isolation**: Filesystem isolation traps, mock fixtures, non-mutating read endpoints, atomic move/rollback operations.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Filesystem Safety Trap & Isolation Guardrails | Create root `tests/conftest.py` with `protect_production_filesystem` (active trap intercepting mutations to `/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`), `isolate_test_environment` (clearing/restoring `os.environ`), and `block_external_network` | M1 | R2, R5, survey |
| F2 | Server Read-Mutation & Latent Defect Remediation | Fix `server.py:1453` `NameError` on `currentExplorerShows`; fix `server.py:581` cumulative `item_count` inflation during read inspection; preserve `server.py` facade re-exports | M1 | R3, survey |
| F3 | Tokenizer Release Year & Numerical Title Disambiguation | Fix left-to-right `RE_YEAR` matching so titles containing numbers (`1917`, `2001`, `1984`, `2049`, `2077`) retain their full title and match actual release year | M2 | R1, survey |
| F4 | Movie Edition & Multi-Part Split Parsing | Add `RE_EDITION` (Director's Cut, Extended, Remastered, Criterion, etc.) and `RE_MOVIE_PART` (`CD1`/`CD2`, `Part 1`, `pt1`); populate `edition`, `part`, `part_label` in `TokenizedFilename` | M2 | R1, survey |
| F5 | TV Roman Numerals, Multi-Episode & Season Pack Parsing | Expand `RE_SEASON_EPISODE` to support Roman numerals (`Season II Episode IV`), multi-episode ranges (`S01E01-E02`, `1x01-02`, `S01E01E02`), and season packs (`Season 01`, `S01 Complete`) | M2 | R1, survey |
| F6 | Daily / Dated Show Parsing | Add `RE_DAILY_DATE` (`YYYY-MM-DD`, `YYYY.MM.DD`) to parse daily broadcast shows; populate `is_daily` and `air_date` in `TokenizedFilename` | M2 | R1, survey |
| F7 | Anime Absolute Numbering & Title Normalization | Upgrade `RE_ANIME_RELEASE` to support parenthesized titles (`(TV)`, `(2014)`), 4-digit absolute numbering (`One Piece - 1088`), batch tags, and cour/season names; populate `absolute_episode` | M2 | R1, survey |
| F8 | Technical Spec Stripping & Normalization Consolidation | Expand audio/video codec and resolution patterns (`10bit`, `HDR`, `HDR10+`, `DV`, `DDP5.1`, `EAC3`, `Opus`, `UHD`); consolidate divergent title cleaners; fix `scanner.py:228` subtitle stem pairing asymmetry | M2 | R1, survey |
| F9 | Season 00 Specials & Multi-Episode Path Naming | Fix `namer.py:164` falsy bug turning Season 0 specials into Season 1; format `S00Exx` and `Season 00` / `Specials`; format multi-episode ranges (`S01E01-E02`); stop injecting `[UnknownGroup]` | M3 | R1, survey |
| F10 | Multi-Part Movie & Daily Show Destination Routing | Support multi-part movie destination paths (`Movie (Year) [Edition] Pt.1.ext`); format daily show destination paths (`Show/Season YYYY/Show - YYYY-MM-DD.ext`) | M3 | R1, survey |
| F11 | Anime Destination Routing & Library Indexing Fix | Fix `ValueError: relative_to(shows_dir)` in `sorter.py:274` when routing anime to `Anime/`; support absolute episode naming templates; fix quarantine double extension (`.mkv.mkv`) in `namer.py:93` | M3 | R1, R3, survey |
| F12 | Endpoint Alias & API Backward Compatibility | Provide `/api/files/scan` alias route to `GET /api/files` with full payload fidelity; verify `/api/files/sort-show` and `/api/library` backward compatibility | M3 | R3, survey |
| F13 | Isolated Automated Verification Suite & Runner | Establish `tests/benchmark/benchmark_cases.py` with 50+ real-world cases across 6 domains, pure in-memory offline runner (`tests/benchmark/test_benchmark.py`), and diagnostic reporting | E2E | R2, survey |
| F14 | Final E2E Benchmark Pass & Adversarial Hardening | Execute full test suite (100% benchmark cases + 75 baseline tests passing cleanly with zero regressions); Tier 5 adversarial stress testing and forensic audit verification | M4 | R2, R3, survey |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | Benchmark Test Suite & Offline Runner | F13 (Benchmark dataset across 6 domains, offline test runner, reporter) -> Publishes `TEST_READY.md` | None | PLANNED |
| M1 | Filesystem Safety Traps & Server Defect Remediation | F1 (`tests/conftest.py` with `protect_production_filesystem`, `isolate_test_environment`, `block_external_network`), F2 (`server.py:1453` NameError fix, `server.py:581` read-mutation fix) | None | PLANNED |
| M2 | Tokenizer Edge-Case Expansion & Pattern Matching | F3 (Year/number disambiguation), F4 (Editions & multi-part), F5 (Roman numerals, multi-ep, season packs), F6 (Daily shows), F7 (Anime absolute numbering), F8 (Technical tag stripping, subtitle pairing) | M1 | PLANNED |
| M3 | Classification, Destination Routing & API Backward Compatibility | F9 (Season 00 specials & multi-ep naming), F10 (Multi-part & daily show destination routing), F11 (Anime routing & library fix, quarantine double ext fix), F12 (`/api/files/scan` alias & API compatibility) | M1, M2 | PLANNED |
| M4 | Final Milestone: Full Benchmark Pass & Adversarial Hardening | F14 (100% pass on benchmark cases + 75 baseline tests, adversarial coverage hardening, forensic audit verification) | E2E, M1, M2, M3 | PLANNED |

## Code Layout
- `src/media_sorter/`
  - `config.py`: Configuration models and settings
  - `models.py`: SQLAlchemy ORM models and `TokenizedMedia` alias
  - `db.py`: Database engine and session factory
  - `scanner.py`: File scanning and sidecar pairing
  - `tokenizer.py`: Filename tokenization, regex parsing, and technical spec normalization
  - `classifier.py`: Media categorization heuristics and confidence scoring
  - `namer.py`: Standardized filename generation and destination path resolution
  - `executor.py`: File moving, copying, and rollback execution
  - `sorter.py`: High-level sorting orchestrator
  - `library.py`: Media library catalog management and disk syncing
  - `quarantine.py`: Quarantine management
  - `server.py`: FastAPI application, route handlers, and UI dashboard
- `tests/`
  - `conftest.py`: Root filesystem safety guardrails, env sanitization, and network blocking
  - `unit/`: Unit tests for core components
  - `integration/`: Integration tests for server and pipeline workflows
  - `benchmark/`: Isolated benchmark verification suite (cases, runner, reporter)

## Interface Contracts
### `tokenizer.py` ↔ `classifier.py`, `namer.py`, `server.py`
- `FilenameTokenizer.tokenize(path: Path) -> TokenizedFilename` (also exported as `TokenizedMedia`)
- Primitive scalar attributes remain `Optional[int]`, `Optional[str]`, `bool`:
  - `title: Optional[str]`, `year: Optional[int]`, `season: Optional[int]`, `episode: Optional[int]`
  - `is_episodic: bool`, `is_anime: bool`
- Extended fields:
  - `multi_episodes: List[int]`
  - `edition: Optional[str]`
  - `part: Optional[int]`, `part_label: Optional[str]`
  - `is_season_pack: bool`, `season_pack_seasons: List[int]`
  - `is_special: bool`, `special_type: Optional[str]`
  - `is_daily: bool`, `air_date: Optional[str]`
  - `absolute_episode: Optional[int]`

### `namer.py` Destination Templates
- Movie: `Movies/{title} ({year})/{title} ({year}) [Edition] [Pt.X].{ext}`
- TV: `TV Shows/{show_name}/Season {season:02d}/{show_name} - S{season:02d}E{episode:02d}.{ext}`
- Specials: `TV Shows/{show_name}/Season 00/{show_name} - S00E{episode:02d}.{ext}`
- Anime: `Anime/{title}/Season {season:02d}/{title} - S{season:02d}E{episode:02d} [{group}].{ext}` or `Anime/{title}/{title} - {abs_episode:02d} [{group}].{ext}`
- Daily Show: `TV Shows/{show_name}/Season {year}/{show_name} - {date}.{ext}`

### `server.py` ↔ External Callers
- `GET /api/files`: Returns `{"downloads": ..., "movies": ..., "shows": ...}`
- `GET /api/files/scan`: Alias to `GET /api/files`
- `POST /api/files/scan`: Alias returning identical file inspection structure
- `POST /api/files/sort-show`: Accepts `SortShowRequest`, returns operations summary
- `GET /api/library`: Returns `{total_shows, total_movies, shows, movies}`
