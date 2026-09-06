# BRIEFING — 2026-09-05T23:53:30Z

## Mission
Investigate Media Sorter's current pattern matching, classification, tokenization, naming, and destination routing logic, identify gaps against R1 requirements, and recommend concrete solutions.

## 🔒 My Identity
- Archetype: explorer
- Roles: investigator, synthesizer
- Working directory: /md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_1
- Original parent: bdb15cd8-994f-440d-978b-c9305f2fc1ae
- Milestone: survey

## 🔒 Key Constraints
- Read-only investigation — do NOT implement or edit source files
- All findings must be backed by direct code observations (file path and line number)
- Deliver findings via handoff report in `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_1/handoff.md` and notify parent via `send_message`

## Current Parent
- Conversation ID: bdb15cd8-994f-440d-978b-c9305f2fc1ae
- Updated: 2026-09-05T23:53:30Z

## Investigation State
- **Explored paths**: `src/media_sorter/tokenizer.py`, `classifier.py`, `namer.py`, `sorter.py`, `scanner.py`, `models.py`, `library.py`, `server.py`, `config.py`, and test suites in `tests/`.
- **Key findings**:
  1. `RE_YEAR.search` matches left-to-right, corrupting titles with 4-digit numbers (1917, 2001, 1984, 2049, 2077).
  2. Movie editions and multi-part files (CD1/CD2, pt1) are not modeled in `TokenizedFilename` and are discarded, causing movie collisions.
  3. `namer.py:164` evaluates `tokens.season or 1`, turning Season 0 specials into Season 1 and overwriting pilots.
  4. Daily/dated TV shows (`2024.03.15`) are misclassified as movies and overwrite each other.
  5. Anime fansub regex disallows `()` in titles; cour/season names and batch releases trigger quarantine; absolute episodes force `S01E1085`.
  6. Quarantine destination paths generate double `.mkv.mkv` extensions.
  7. `sorter.py:276` crashes with `ValueError` on anime paths relative to `shows_dir`, silently dropping anime from library records.
  8. `scanner.py:228` only tests `s_stem.startswith(c_stem)`, failing to pair clean subtitles with tagged videos.
  9. `namer.py:187` defaults `group` to `"UnknownGroup"`, rendering unwanted `[UnknownGroup]` in filenames.
- **Unexplored areas**: None within survey scope.

## Key Decisions Made
- Completed systematic empirical survey of all 8 core pipeline modules.
- Delivered detailed 5-component handoff report to `handoff.md`.

## Artifact Index
- `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_1/handoff.md` — 5-component survey and recommendations report
- `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_1/progress.md` — Progress tracker and heartbeat
- `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_1/DISPATCH.md` — Parent dispatch record
