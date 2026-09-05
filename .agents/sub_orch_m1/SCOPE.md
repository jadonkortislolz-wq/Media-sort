# Scope: Milestone 1 — Filesystem Safety Guardrails & Database Reliability Hardening

## Architecture
- Root `tests/conftest.py`: Autouse filesystem safety trap preventing writes to `/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`. Clean `os.environ` isolation.
- `src/media_sorter/db.py`: Singleton engine / sessionmaker registry, proper `get_db_session` context manager with commit/rollback/close and `scoped_session.remove()` semantics.
- `src/media_sorter/sorter.py`: Concurrency lock on `rollback()` and `rollback_all()`. Fix `op.status` reference on `PlannedOperation`.
- `src/media_sorter/server.py`: Concurrency lock on manual sort routes. Remove mutating side-effects from `GET /api/files` (`inspect_downloads_folder` should not alter `library_items` counts). Run `auto_sort_worker` in threadpool (`run_in_threadpool`).
- `src/media_sorter/executor.py`: Transactional rollback state in `rollback_batch()`.
- `src/media_sorter/quarantine.py`: Transactional `undo_item()` committing only on successful file move.
- `alembic/versions/`: Migration ensuring `library_items` table schema exists.

## Milestones (Internal to M1)
| # | Task | Scope | Status |
|---|------|-------|--------|
| M1-1 | Filesystem Trap & Env Sanitization | `tests/conftest.py` with mock protection and environment isolation | PLANNED |
| M1-2 | Database Session & Engine Refactoring | `db.py` session factory, pooling, and context manager | PLANNED |
| M1-3 | Concurrency Locks & Async Worker Offload | Locking on rollback/manual sort, `run_in_threadpool` for auto-sort | PLANNED |
| M1-4 | Transactional Fixes & Schema Sync | `op.status` fix in sorter, Alembic migration for `library_items`, rollback batch atomicity | PLANNED |
| M1-5 | Read-Endpoint Side-Effect Removal | Purge mutation from `GET /api/files` | PLANNED |
| M1-6 | Verification & Audit Gate | 75 baseline tests pass + new DB tests pass + Forensic Auditor verification | PLANNED |
