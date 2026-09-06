## 2026-09-05T23:49:43Z

Your working directory is: /md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_1
The authoritative original request is: /md0/media-sorter/.agents/ORIGINAL_REQUEST.md
You MUST read /md0/media-sorter/.agents/ORIGINAL_REQUEST.md before starting work.

Mission:
Investigate Media Sorter's current pattern matching, classification, tokenization, naming, and destination routing logic.

Scope:
1. Examine `src/media_sorter/tokenizer.py`, `classifier.py`, `namer.py`, `sorter.py`, `scanner.py`, `models.py`, and any related modules.
2. Analyze current capabilities and gaps for:
   - Movies: release years (e.g. `Movie.Title.2023.1080p`), editions (e.g. `Director's Cut`, `Extended`, `Remastered`, `Criterion`), multi-part movies (e.g. `Part 1`, `CD1`, `pt1`).
   - TV Shows: standard `SxxExx`, season packs (`Season 01`, `S01 Complete`), specials (`S00Exx`, `Special`, `OVA`, `SP`), daily/dated shows (`2024-03-15`, `2024.03.15`).
   - Anime formats: absolute episode numbering (e.g. `[SubsPlease] Title - 05 [1080p]`, `[Erai-raws] Title - 105`), batch tags, resolution tokens, season/cour names.
   - Normalization: stripping resolution tokens (`1080p`, `4K`, `2160p`, `720p`), audio codecs (`AAC`, `DTS-HD`, `FLAC`, `AC3`), release groups (`[Group]` or `-Group`), and complex punctuation without losing title or episode information.
   - Destination path generation in `namer.py` and `sorter.py`: how files are routed to `Movies/Title (Year)/Title (Year) [Edition].ext` or `TV Shows/Title/Season XX/Title - SxxExx.ext` or `Anime/Title/Title - E05.ext`, etc.
3. Check existing data structures: `TokenizedMedia`, `MediaClassifier`, `MediaNamer`, `MediaType`, and identify what new fields or methods are needed.
4. Produce a detailed handoff report in `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_2_1/handoff.md` with:
   - Existing pattern regexes and logic
   - Identified gaps against R1 requirements
   - Concrete recommendations for regex patterns, data structures, and destination routing logic
   - Code locations and lines of interest.
Remember: You are read-only. Do NOT edit source files. Write your progress to progress.md and your report to handoff.md.
