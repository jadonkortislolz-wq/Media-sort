# Dispatch: Explorer M1-1 (Filesystem Trap & Env Sanitization Design)

## Mission
Design the concrete implementation for `tests/conftest.py` providing:
1. Production filesystem safety trap: An `autouse=True` fixture that hooks filesystem operations (`open`, `os.remove`, `os.unlink`, `os.rmdir`, `os.rename`, `shutil.move`, `shutil.rmtree`, `Path.unlink`, `Path.rmdir`, `Path.rename`, `Path.mkdir`, `Path.open`) to block any write/mutation targeting `/md0/jdownloads`, `/md0/movies1`, or `/md0/tv1` (and any subdirectory thereof) by raising `RuntimeError("Filesystem Safety Violation: Write attempt to production path...")`.
2. Environment isolation: Ensure tests do not leak environment variables (specifically `CONFIDENCE_THRESHOLD` or other settings from `/api/settings`) into other test cases.
3. Verify compatibility with existing 75 tests and any upcoming test fixtures.

## Mandatory Reading
- `/md0/media-sorter/ORIGINAL_REQUEST.md`
- `/md0/media-sorter/PROJECT.md`
- `/md0/media-sorter/.agents/sub_orch_m1/SCOPE.md`
- `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_3/report.md`

## Output
Write your analysis and precise implementation design to `/md0/media-sorter/.agents/teamwork_preview_explorer_m1_1/report.md` and handoff summary to `handoff.md`. Notify orchestrator when complete.

## 2026-09-05T18:53:51Z
You are Explorer M1-1 (Filesystem Trap & Env Sanitization Design).
Your working directory is: /md0/media-sorter/.agents/teamwork_preview_explorer_m1_1
Your dispatch instructions are at: /md0/media-sorter/.agents/teamwork_preview_explorer_m1_1/DISPATCH.md
MANDATORY: Read /md0/media-sorter/ORIGINAL_REQUEST.md and /md0/media-sorter/PROJECT.md before starting work.

Design the concrete implementation for tests/conftest.py:
1. Autouse filesystem safety trap intercepting writes, unlinks, rmdirs, renames to /md0/jdownloads, /md0/movies1, /md0/tv1, raising RuntimeError.
2. Global environment variable isolation (preventing /api/settings from leaking CONFIDENCE_THRESHOLD into other tests).
3. Test compatibility with existing 75 baseline tests.

Write detailed design to /md0/media-sorter/.agents/teamwork_preview_explorer_m1_1/report.md and deliver handoff.md. Send completion message when finished.
