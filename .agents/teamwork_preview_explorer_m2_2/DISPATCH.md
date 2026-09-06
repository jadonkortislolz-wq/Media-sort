## 2026-09-06T02:36:00Z
You are teamwork_preview_explorer_m2_2, an Explorer agent.
Working directory: /md0/media-sorter/.agents/teamwork_preview_explorer_m2_2

Authoritative sources of truth to read:
1. MANDATORY: /md0/media-sorter/.agents/ORIGINAL_REQUEST.md
2. /md0/media-sorter/PROJECT.md
3. /md0/media-sorter/TEST_READY.md
4. src/media_sorter/classifier.py
5. src/media_sorter/namer.py
6. tests/benchmark/cases.py, tests/unit/test_classifier.py, tests/unit/test_namer.py

Objective:
Investigate and design precise enhancements for media classification and standardized destination naming in classifier.py and namer.py:
1. Classification heuristics:
   - Daily / dated broadcast TV shows vs movies: ensure dated shows are classified as 'tv' (not 'movie') while podcasts are classified as 'podcast'.
   - Anime classification: ensure keyword 'Episode', cour tags, OVA specials, and absolute numbering are properly classified as 'anime'.
   - Calibration of weights/scores to ensure accurate categorization across all 64 benchmark cases without regressions on existing 82 tests.
2. Destination naming in namer.py:
   - Fix Season 00 falsy bug: ensure `tokens.season is not None` so Season 00 specials are preserved as 'Season 00' instead of defaulting to Season 01.
   - Standard TV destination template: 'TV Shows/{show_name}/Season {season:02d}/{show_name} - S{season:02d}E{episode:02d}.ext' (supporting multi-episode 'S04E01-E02').
   - Movie destination formatting: 'Movies/{title} ({year})/{title} ({year}) [Edition] [Pt.X].ext'.
   - Anime destination formatting: 'Anime/{title}/{title} - {episode} [{group}].ext' (omit group tag if unknown, never emit '[UnknownGroup]').
   - Daily TV destination formatting: 'TV Shows/{show_name}/Season {year}/{show_name} - {date}.ext'.
   - Subtitle pairing and language suffix preservation (e.g. '.forced.srt', '.en.srt').
   - Behind-the-scenes and extras suffixes ('-behindthescenes', '-deleted', '-trailer', '-featurette').

Strict Constraints:
- DO NOT modify or write any source code files.
- Write your full analysis report to /md0/media-sorter/.agents/teamwork_preview_explorer_m2_2/analysis.md
- Write your handoff summary to /md0/media-sorter/.agents/teamwork_preview_explorer_m2_2/handoff.md
- Use send_message to notify parent when complete.
