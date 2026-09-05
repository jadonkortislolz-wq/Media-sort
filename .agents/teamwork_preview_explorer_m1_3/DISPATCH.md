# Dispatch: Explorer M1-3 (Concurrency, Rollback & Read Side-Effect Elimination)

## Mission
Design the concrete refactoring for concurrency locking, transaction rollback integrity, and side-effect elimination:
1. `src/media_sorter/sorter.py`:
   - Concurrency locking: `sorter.rollback()` and `sorter.rollback_all()` must acquire the process lock (same lock as `sorter.run()`) to prevent race conditions against active background sort runs.
   - Fix `op.status` bug at line 271: `PlannedOperation` has no `status` attribute. Check the operation execution results or report status to properly record committed operations into `LibraryItem`.
2. `src/media_sorter/server.py`:
   - Acquire lock on manual sort routes (`/api/files/manual-sort`, `/api/files/sort-show`, `/api/files/sort-group`).
   - Remove mutating side effects from `GET /api/files`: `inspect_downloads_folder` must be a pure read operation without mutating `library_items` counts.
   - Run `auto_sort_worker` using `starlette.concurrency.run_in_threadpool` (or `asyncio.to_thread`) so synchronous file I/O does not block FastAPI's async event loop.
3. `src/media_sorter/executor.py` & `src/media_sorter/quarantine.py`:
   - `rollback_batch()`: ensure partial failure during rollback marks the batch with `PARTIAL_FAILED` or raises rather than unconditionally setting `status = "ROLLED_BACK"`.
   - `undo_item()` in quarantine: ensure database commit only occurs if `shutil.move` actually succeeded.

## Mandatory Reading
- `/md0/media-sorter/ORIGINAL_REQUEST.md`
- `/md0/media-sorter/PROJECT.md`
- `/md0/media-sorter/.agents/sub_orch_m1/SCOPE.md`
- `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_2/report.md`
- `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_3/report.md`

## Output
Write your analysis and precise implementation design to `/md0/media-sorter/.agents/teamwork_preview_explorer_m1_3/report.md` and handoff summary to `handoff.md`. Notify orchestrator when complete.

## 2026-09-05T18:53:51Z
You are Explorer M1-3 (Concurrency, Rollback & Read Side-Effect Elimination).
Your working directory is: /md0/media-sorter/.agents/teamwork_preview_explorer_m1_3
Your dispatch instructions are at: /md0/media-sorter/.agents/teamwork_preview_explorer_m1_3/DISPATCH.md
MANDATORY: Read /md0/media-sorter/ORIGINAL_REQUEST.md and /md0/media-sorter/PROJECT.md before starting work.

Design the concrete refactoring for:
1. Concurrency locking on sorter.rollback(), rollback_all(), and manual sort routes.
2. Fix op.status AttributeError bug at sorter.py:271 so live sorts update LibraryItem.
3. Remove mutating side-effects from GET /api/files (inspect_downloads_folder).
4. Offload synchronous sorter.run() in auto_sort_worker from FastAPI event loop.
5. Transactional rollback batch status in executor.py and undo_item in quarantine.py.

Write detailed design to /md0/media-sorter/.agents/teamwork_preview_explorer_m1_3/report.md and deliver handoff.md. Send completion message when finished.
