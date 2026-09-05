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
