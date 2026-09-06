## 2026-09-06T02:41:24Z
You are teamwork_preview_worker_m2, a Worker agent.
Working directory: /md0/media-sorter/.agents/teamwork_preview_worker_m2

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Authoritative source of truth to read first:
1. MANDATORY: /md0/media-sorter/.agents/ORIGINAL_REQUEST.md
2. /md0/media-sorter/PROJECT.md
3. /md0/media-sorter/TEST_READY.md
4. Explorer reports:
   - /md0/media-sorter/.agents/teamwork_preview_explorer_m2_1/analysis.md and handoff.md and test_enhanced_prototype.py
   - /md0/media-sorter/.agents/teamwork_preview_explorer_m2_2/analysis.md and handoff.md
   - /md0/media-sorter/.agents/teamwork_preview_explorer_m2_3/analysis.md and handoff.md

Write Ownership:
You have exclusive write ownership of:
- `src/media_sorter/tokenizer.py`
- `src/media_sorter/classifier.py`
- `src/media_sorter/namer.py`
- `src/media_sorter/scanner.py`
- `src/media_sorter/executor.py`
- `src/media_sorter/db.py`
- `src/media_sorter/server.py` (specifically for manual-sort sanitization, poster security bounds, and concurrency locks)
- Any unit/integration test files in `tests/` needed to verify your changes.

Objectives:
Implement the synthesized designs from the three Explorers:
1. Tokenizer enhancements in `src/media_sorter/tokenizer.py`:
   - Extend `TokenizedFilename` with `edition`, `part`, `part_label`, `air_date`, `is_daily`, `is_season_pack`, `multi_episodes: List[int]`
   - Ambiguous numerical titles vs release years (right-to-left year extraction before tech specs)
   - Roman numerals for TV seasons/episodes
   - Multi-episode ranges (`S04E01-E02`, `2x01-02`, `S03E01E02`, `S06E15-E16`)
   - Season packs (`Succession.S02.Complete`)
   - Movie editions (`Extended`, `Director's Cut`, `Remastered`, `Criterion`, `Final Cut`) and multi-part CD1/CD2/Pt.1/Pt.2
   - Daily broadcast dates (`YYYY-MM-DD`, `YYYY.MM.DD`, `YYYY_MM_DD`)
   - Anime parenthesized title years (`Fairy Tail (2014)`), 4-digit absolute numbering (`One Piece - 1088`), cour tags, OVA specials, multi-episode anime
   - Underscore normalization and messy character cleaning

2. Classification and Naming enhancements in `src/media_sorter/classifier.py` and `src/media_sorter/namer.py`:
   - In `classifier.py`: daily broadcast TV shows get `is_tv = True` and release year movie boost suppressed; audio files with date stamps get classified as `podcast`; anime classification recognized without scene group false positives.
   - In `namer.py`: fix Season 00 / Episode 00 falsy bug (`if tokens.season is not None`); standardize TV template to `{show_name}/Season {season:02d}/{show_name} - S{season:02d}E{episode:02d}.ext` (with multi-episode and season pack support); movie destination `{title} ({year})/{title} ({year}) [Edition] [Pt.X].ext` with extras suffixes (`-behindthescenes`, etc.); flat anime destination `Anime/{title}/{title} - {episode} [{group}].ext` (omit `[UnknownGroup]`); daily TV destination `TV Shows/{show_name}/Season {year}/{show_name} - {date}.ext`; subtitle compound suffix preservation (`.forced.srt`, `.en.srt`).

3. Companion files, security, and database hardening:
   - In `scanner.py`: candidate length sorting and delimiter boundary checks in `_pair_sidecars`.
   - In `executor.py`: link sidecars to primary files so conflict renames update sidecar destinations; cross-device safe rollback (`_safe_move`); `PARTIAL_ROLLBACK` status on partial failures.
   - In `db.py`: engine-cached `scoped_session` with `remove()`; 30000ms busy timeout on SQLite WAL.
   - In `server.py`: sanitize `req.title` in `/api/files/manual-sort` and handle Windows reserved names (`CON.mp4 -> _CON.mp4`); restrict `/api/poster/local` to configured media storage paths (HTTP 403 on path traversal).

Verification & Completion:
1. Run the existing test suite: `.venv/bin/pytest tests/unit/ tests/integration/` (must achieve 100% pass rate).
2. Run the benchmark runner: `.venv/bin/python -m tests.benchmark.runner` and `.venv/bin/pytest tests/benchmark/test_benchmark.py` (verify high pass rate or 100%).
3. Verify filesystem safety traps are respected (0 writes to `/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`).
4. Write your comprehensive handoff report to `/md0/media-sorter/.agents/teamwork_preview_worker_m2/handoff.md`.
5. Send a completion message back to parent when done.
