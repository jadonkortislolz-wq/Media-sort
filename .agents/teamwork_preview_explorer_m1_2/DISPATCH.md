# Dispatch: Explorer M1-2 (Database Session, Engine & Migration Design)

## Mission
Design the concrete refactoring for `src/media_sorter/db.py` and Alembic migrations:
1. `src/media_sorter/db.py`:
   - Eliminate the anti-pattern of creating a new `scoped_session` on every `get_db_session()` call.
   - Implement singleton / cached engine creation with connection pooling (`QueuePool` or `StaticPool` for in-memory).
   - Provide a clean `get_db_session(engine: Engine)` context manager yielding a `Session`, committing on success, rolling back on error, closing properly, and removing thread-local session scope if `scoped_session` is used.
2. Alembic migration:
   - Provide an Alembic migration script (or update initial schema) to ensure `library_items` table is created in Alembic migration history, so `alembic upgrade head` creates all 6 tables: `batches`, `files`, `quarantine`, `config_audit`, `operations`, `library_items`.
3. Database tests:
   - Design unit tests for session lifecycle, concurrent session creation, rollback safety, and connection pool behavior in `tests/unit/test_db_hardening.py`.

## Mandatory Reading
- `/md0/media-sorter/ORIGINAL_REQUEST.md`
- `/md0/media-sorter/PROJECT.md`
- `/md0/media-sorter/.agents/sub_orch_m1/SCOPE.md`
- `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_2/report.md`

## Output
Write your analysis and precise implementation design to `/md0/media-sorter/.agents/teamwork_preview_explorer_m1_2/report.md` and handoff summary to `handoff.md`. Notify orchestrator when complete.

## 2026-09-05T18:53:51Z
You are Explorer M1-2 (Database Session, Engine & Migration Design).
Your working directory is: /md0/media-sorter/.agents/teamwork_preview_explorer_m1_2
Your dispatch instructions are at: /md0/media-sorter/.agents/teamwork_preview_explorer_m1_2/DISPATCH.md
MANDATORY: Read /md0/media-sorter/ORIGINAL_REQUEST.md and /md0/media-sorter/PROJECT.md before starting work.

Design the concrete refactoring for:
1. src/media_sorter/db.py: eliminate scoped_session re-creation on every call; implement engine caching, connection pooling, and proper context-managed get_db_session with commit/rollback/close and scoped_session.remove().
2. Alembic migration for library_items table so alembic upgrade head creates all 6 tables.
3. Unit tests for database session lifecycle and transaction safety in tests/unit/test_db_hardening.py.

Write detailed design to /md0/media-sorter/.agents/teamwork_preview_explorer_m1_2/report.md and deliver handoff.md. Send completion message when finished.
