## 2026-09-05T23:49:43Z

Your working directory is: /md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_3
The authoritative original request is: /md0/media-sorter/.agents/ORIGINAL_REQUEST.md
You MUST read /md0/media-sorter/.agents/ORIGINAL_REQUEST.md before starting work.

Mission:
Investigate Media Sorter's REST API endpoints, UI operations, and backward compatibility requirements.

Scope:
1. Examine `src/media_sorter/server.py` and `src/media_sorter/routes/` (e.g. `files.py`, `library.py`, `status.py`, `batches.py`, etc.).
2. Specifically inspect the target endpoints mentioned in R3:
   - `/api/files/scan`
   - `/api/files/sort-show`
   - `/api/library`
   - Any other sorting or file inspection endpoints (`/api/files`, `/api/run`, `/api/files/manual-sort`, etc.)
3. Trace how filenames are processed in these endpoints:
   - How does `/api/files/scan` return classified items or detected media types?
   - How does `/api/files/sort-show` handle custom destination or series grouping?
   - How does `/api/library` store and return library items, show names, seasons, and media types?
4. Identify any potential regressions or breaking changes if `tokenizer.py`, `classifier.py`, or `namer.py` are modified (e.g. changes in `TokenizedMedia`, return schemas, destination paths, database `media_type` values).
5. Produce a detailed handoff report in `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_3/handoff.md` with:
   - Endpoint contract analysis and payload schemas
   - Exact lines where tokenization/classification/naming are called in routes
   - Safe extension points to ensure 100% backward compatibility
   - Verification tests needed to guarantee no regressions.
Remember: You are read-only. Do NOT edit source files. Write your progress to progress.md and your report to handoff.md.
