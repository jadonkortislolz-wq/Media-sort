# Dispatch: Milestone 1 Sub-Orchestrator (Filesystem Safety & Database Reliability)

## Mission
You are the Sub-Orchestrator for Milestone 1: Filesystem Safety Guardrails & Database Reliability Hardening.
Your working directory is: /md0/media-sorter/.agents/sub_orch_m1
Your scope document is: /md0/media-sorter/.agents/sub_orch_m1/SCOPE.md
Project specification: /md0/media-sorter/PROJECT.md
Authoritative request: /md0/media-sorter/ORIGINAL_REQUEST.md
Survey findings:
- Database: /md0/media-sorter/.agents/teamwork_preview_explorer_survey_2/report.md
- Filesystem safety: /md0/media-sorter/.agents/teamwork_preview_explorer_survey_3/report.md
Your parent is: orchestrator_1 (dd8d62a8-8522-473a-8123-8f8d672e10a1)

## Scope & Assigned Features
You own implementation and verification of:
1. **F10: Filesystem Safety Guardrails & Environment Isolation (R5)**
   - Add root `tests/conftest.py` with an `autouse=True` fixture that traps and blocks any write/unlink/mkdir operations targeting `/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`, raising `RuntimeError`.
   - Decouple `Settings` from process-wide `os.environ` mutations in `/api/settings` to prevent cross-test environment contamination.
2. **F4: Database Session Lifecycle & Engine Management (R2)**
   - Eliminate broken `scoped_session` re-instantiation in `src/media_sorter/db.py`.
   - Implement clean connection pooling, engine management, and context-managed sessions (`session.close()`, `remove()`).
3. **F5: Database Transaction Safety & Concurrency Hardening (R2)**
   - Add concurrency locking on rollback (`sorter.rollback()`) and manual sort operations to prevent race conditions against active background sort runs.
   - Fix partial rollback state in `src/media_sorter/executor.py:rollback_batch()`.
   - Fix non-transactional `undo_item()` in `src/media_sorter/quarantine.py`.
   - Offload synchronous `sorter.run()` from the FastAPI async event loop in `auto_sort_worker`.
4. **F6: Schema Synchronization & Library Catalog Integrity (R2)**
   - Add missing `library_items` table to Alembic migrations.
   - Fix silent `AttributeError` on `op.status` in `src/media_sorter/sorter.py:271` so live sorts correctly update `LibraryItem` entries.
   - Remove read-endpoint mutation in `GET /api/files` that cumulatively inflates `item_count`.

## Execution Workflow
Execute the standard iteration loop (Explorer -> Worker -> Reviewer -> Challenger -> Auditor -> Gate).
When all acceptance checks pass and the audit is CLEAN, update `SCOPE.md` and report completion back to parent orchestrator.
