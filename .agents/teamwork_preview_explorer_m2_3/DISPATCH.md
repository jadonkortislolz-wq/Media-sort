## 2026-09-06T02:36:00Z

<USER_REQUEST>
You are teamwork_preview_explorer_m2_3, an Explorer agent.
Working directory: /md0/media-sorter/.agents/teamwork_preview_explorer_m2_3

Authoritative sources of truth to read:
1. MANDATORY: /md0/media-sorter/.agents/ORIGINAL_REQUEST.md
2. /md0/media-sorter/PROJECT.md
3. src/media_sorter/scanner.py, src/media_sorter/executor.py, src/media_sorter/server.py
4. src/media_sorter/quarantine.py, src/media_sorter/library.py, src/media_sorter/db.py
5. tests/unit/test_scanner.py, tests/unit/test_executor.py, tests/unit/test_server_and_env.py

Objective:
Investigate and design robust implementations for companion file handling, input validation, and database safety:
1. Companion file handling & cleanup:
   - Verify sidecar pairing (.srt, .sub, .ass, .nfo) in scanner.py and executor.py.
   - Ensure companion files move atomically with primary video files.
   - Verify folder cleanup logic removes empty directories safely.
   - Folder Explorer exclusions: confirm .txt and .srt exclusion rules in file exploration.
2. Input sanitization & security guardrails in server.py:
   - Sanitize user-supplied filenames in /api/files/manual-sort (strip forbidden characters `: * ? " < > |`).
   - Windows reserved device names (e.g. CON.mp4 -> _CON.mp4, NUL, AUX, PRN, COM1-9, LPT1-9).
   - Storage boundary checks in /api/poster/local to prevent path traversal.
3. Database & transaction scoping:
   - Rollback mechanics in executor.py: ensure batch history correctly tracks all moved files and rollback restores them completely.
   - SQLite WAL concurrency and session scoping in db.py: verify scoped_session cleanup, thread safety, and no connection leaks.
   - Concurrency locking during sort runs and rollbacks.

Strict Constraints:
- DO NOT modify or write any source code files.
- Write your full analysis report to /md0/media-sorter/.agents/teamwork_preview_explorer_m2_3/analysis.md
- Write your handoff summary to /md0/media-sorter/.agents/teamwork_preview_explorer_m2_3/handoff.md
- Use send_message to notify parent when complete.
</USER_REQUEST>
