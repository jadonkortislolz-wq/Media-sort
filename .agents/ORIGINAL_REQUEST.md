# Original User Request

## Initial Request — 2026-09-05T18:48:23Z

Conduct a comprehensive codebase audit, architectural decoupling, database transaction hardening, and test suite expansion for the Media Sorter application to ensure production-grade reliability, modularity, and maintainability.

Working directory: /md0/media-sorter
Integrity mode: development

## Requirements

### R1. Architectural Decoupling and Modularity
Audit the codebase and decompose monolithic components (notably server orchestration, UI template rendering, and endpoint handling) into clean, decoupled modules with clear separation of concerns, while maintaining strict backward compatibility with the existing single-page web dashboard and REST API contract.

### R2. Database Reliability and Transactional Safety
Harden database session management, connection pooling, and error handling across concurrent requests, ensuring clean lifecycle scoping (preventing generator/context manager misuse, uncommitted mutations, or leaked connections) and robust transaction rollback resilience.

### R3. Error Handling and Input Validation
Harden all API endpoints and sorting pipelines with rigorous data validation, clear structured error reporting, and defensive fallbacks to handle malformed inputs, unreachable paths, and unexpected filesystem states gracefully without crashing the service.

### R4. Test Suite Expansion and Edge-Case Coverage
Expand the automated test suite with extensive unit, property-based, and edge-case integration tests covering complex media filenames (anime release tags, roman numerals, multi-part episodes, ambiguous years), concurrent sort operations, and mock filesystem isolation.

### R5. Controlled Infrastructure and Filesystem Safety Guardrails
All file manipulation and verification tests must execute within isolated temporary test fixtures. The system must never mutate or delete real user media files in production directories (`/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`) during testing or audit execution.

## Acceptance Criteria

### Test Verification & Quality
- [ ] `pytest tests/` runs with a 100% pass rate across all existing 75 unit/integration tests and any newly added tests with zero regressions.
- [ ] Core sorting, tokenization, database, and API routing modules achieve or exceed 90% test coverage.
- [ ] All new and modified tests use isolated mock directories or temporary fixtures without touching real user media paths.
- [ ] Static syntax, import integrity, and code quality checks pass cleanly.

### Functional & Contract Compatibility
- [ ] All existing REST API endpoints (`/api/status`, `/api/files`, `/api/run`, `/api/rollback`, `/api/library`, `/api/quarantine`, etc.) remain 100% backward-compatible in request signatures and response schemas.
- [ ] Single-page web dashboard remains fully functional, retaining Folder Explorer (with `.txt`/`.srt` exclusions), Library catalog views, quarantine queue, theme dropdown & swatches, and manual classification modals.
- [ ] Existing companion file behaviors (subtitle pairing and cleanup routines) function without regressions.

## Follow-up — 2026-09-05T23:48:06Z

Expand Media Sorter's automated media sorting rules, classification edge-case handling (TV series, Anime, Movies, multi-part episodes, specials, year tags), and build a comprehensive automated test suite and regression benchmark.

Working directory: /md0/media-sorter
Integrity mode: development

## Requirements

### R1. Robust Pattern Matching & Categorization
Expand media classification and destination routing to reliably distinguish between:
- Movies (including release years, editions, multi-part movies)
- TV Shows (standard SxxExx, season packs, specials, daily/dated shows)
- Anime formats (absolute episode numbers, batch tags, resolution tokens)
Ensure filenames with resolution tags (e.g. 1080p, 4K), audio codecs, release groups, and complex punctuation are accurately normalized without losing episode or title details.

### R2. Isolated Automated Verification Suite
Develop a repeatable test suite testing classification, parsing, and destination resolution against a diverse benchmark dataset of real-world media filename patterns.
- Tests must run offline without requiring external network connectivity or mutations to real media storage folders.
- Provide clear reporting on passed, failed, and edge-case classifications.

### R3. Safe Backward Compatibility
Ensure existing UI operations and server API endpoints (`/api/files/scan`, `/api/files/sort-show`, `/api/library`) continue functioning seamlessly with any pattern parser enhancements.

## Acceptance Criteria

### Test Execution
- [ ] An automated test suite command (e.g., `pytest` or a test runner script) executes cleanly within the workspace.
- [ ] 100% of benchmark test cases pass with zero unhandled exceptions.
- [ ] No regression on existing sorting endpoints or file categorization routes.

## Follow-up — 2026-09-06T02:34:04Z

Conduct a comprehensive feature enhancement, architectural decoupling, and thorough automated bug testing suite execution for the Media Sorter application.

Working directory: /md0/media-sorter
Integrity mode: development

## Requirements

### R1. Architectural Decoupling & Server Modularity
Decompose monolithic components (server routing, API endpoints, file operations) into decoupled, maintainable modules while preserving complete backward compatibility with the existing single-page web dashboard and REST API contract.

### R2. Robust Media Classification & Edge-Case Sorting
Enhance pattern matching and metadata extraction to accurately categorize complex real-world media:
- Standard Movies and TV series (including season/episode tags, resolutions, and audio codecs)
- Anime releases (absolute episode numbering, release group tags)
- Multi-part episodes, specials, and dated daily shows
Ensure companion files (subtitles .srt, .sub) and folder cleanups function reliably.

### R3. Resilient Database & Transaction Scoping
Harden SQLite WAL database operations, batch history tracking, and rollback mechanics to guarantee transactional integrity and prevent data corruption during concurrent operations.

### R4. Comprehensive Bug Testing & Verification Suite
Audit and test the entire application pipeline against edge-case filenames, malformed inputs, unreachable paths, and concurrent requests with isolated mock fixtures.

## Acceptance Criteria

### Verification & Bug Testing
- [ ] Automated test suite (`pytest tests/`) passes 100% across all unit, integration, and safety tests with zero unhandled exceptions.
- [ ] Media classification and tokenizer handle standard, anime, movie, special, and messy filename patterns accurately.
- [ ] Rollback mechanics correctly restore moved files across individual batches and full batch histories.
- [ ] Filesystem safety guardrails ensure zero mutations or deletions to external production media directories during testing.

### Functional & Contract Compatibility
- [ ] All REST API endpoints (`/api/status`, `/api/files`, `/api/run`, `/api/rollback`, `/api/library`, `/api/quarantine`, etc.) remain 100% backward-compatible in request signatures and response schemas.
- [ ] Single-page web dashboard remains fully functional, retaining Folder Explorer (with `.txt`/`.srt` exclusions), Library catalog views, quarantine queue, all 30 CSS themes, RGB Chroma mode, and classification modals.
