# Dispatch for Explorer 3 (Survey: Sorting Pipeline, Companion Files & Filesystem Safety)

## Mission
Investigate the media sorting pipeline, tokenization and filename parsing, companion file handling, error handling, input validation, and filesystem safety guardrails.

## Input Context
- User request: `/md0/media-sorter/ORIGINAL_REQUEST.md`
- Codebase root: `/md0/media-sorter`
- Working directory: `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_3`

## Specific Investigation Tasks
1. Map the sorting pipeline from scanning source paths to classification, file moving, companion file pairing, and database logging.
2. Analyze media tokenization and filename parsing: regexes, tokenizers, classification algorithms (movies vs TV vs anime, season/episode detection, roman numerals, multi-part episodes, release tags, ambiguous years).
3. Analyze companion file handling: subtitle pairing (`.srt`, `.sub`, etc.), metadata/info files (`.nfo`, `.txt`), exclusions, and cleanup routines.
4. Examine error handling, path validation, and defensive fallbacks: how unreachable paths, permission errors, malformed inputs, and filesystem collisions are handled.
5. Examine filesystem safety: identify any references to real user media paths (`/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`) and how tests/production code separate real vs mock paths to fulfill R5.

## Output
Write your comprehensive survey report to `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_3/report.md` and handoff summary to `handoff.md`.
