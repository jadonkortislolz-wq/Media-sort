# Handoff Report: Tokenizer Regex Enhancements & Tokenization Logic (M2)

**Agent**: teamwork_preview_explorer_m2_1  
**Recipient**: parent (55e25733-b82c-41da-a4ba-b46248b75abb)  
**Date**: 2026-09-06  
**Type**: Hard Handoff (Task Complete)  

---

## 1. Observation

### Direct Code & Test Observations
1. **Current Benchmark State**:
   - Running `.venv/bin/python -m tests.benchmark.runner --no-diffs` produced:
     ```
     Total Cases: 64 | Passed: 1 | Failed: 63 | Pass Rate: 1.6%
     Standard TV: 0/11 | Anime: 0/11 | Movies: 0/14 | Specials & Extras: 0/9 | Daily / Dated Shows: 0/9 | Messy & Complex: 1/10
     ```
   - Only `MESSY-06` (`The.Dark.Knight.2008.1080p.forced.srt`) passed in the baseline.
2. **Tokenizer Mismatches**:
   - Systematic evaluation across `tests/benchmark/benchmark_cases.py` revealed **27 direct field mismatches** originating in `src/media_sorter/tokenizer.py`:
     - Ambiguous numerical titles: `MOVIE-02` (`1917.2019.mkv`) extracted `title=""`, `year=1917` (expected: `title="1917"`, `year=2019`).
     - Future/past years in title: `MOVIE-04` (`Blade.Runner.2049.2017.mkv`) extracted `title="Blade Runner"`, `year=2049` (expected: `title="Blade Runner 2049"`, `year=2017`); `MOVIE-05` (`Wonder.Woman.1984.2020.mkv`) extracted `title="Wonder Woman"`, `year=1984` (expected: `title="Wonder Woman 1984"`, `year=2020`).
     - Movie editions & split parts: `MOVIE-03`, `MOVIE-10` to `MOVIE-14`, `MESSY-01` lacked `edition` attribute in `TokenizedFilename`; `MOVIE-07` and `MOVIE-08` lacked `part` attribute, causing path collision.
     - Roman numerals: `TV-06` (`Rome.Season.II.Episode.IV.mkv`) had `season=None`, `episode=None` because `RE_SEASON_EPISODE` only accepted `\d{1,2}`.
     - Multi-episode range: `TV-05` (`The.Office.2x01-02.mkv`) was captured by `RE_ANIME_RELEASE` as title `The Office 2x01`, episode `2`.
     - Season packs: `TV-08` (`Succession.S02.Complete.mkv`) lacked season/episode extraction.
     - Daily dated shows: `DAILY-01` to `DAILY-08` lacked `RE_DAILY_DATE` parsing; year was misidentified as movie year, causing TV shows to be categorized as movies.
     - Anime parenthesized years: `ANIME-03` (`[HorribleSubs] Fairy Tail (2014) - 176.mkv`) was rejected by `RE_ANIME_RELEASE` because `[^\[\]\(\)]+?` forbade parentheses in titles.
     - Underscore word boundaries: `MESSY-10` (`Show_Name__2022__S02E03__HDTV.mkv`) failed `RE_YEAR` because Python's `\b` considers `_` a word character (`\w`), preventing boundary detection in `__2022__`.
3. **Existing Regression Suite**:
   - Running `.venv/bin/pytest tests/unit/ tests/integration/` showed **83 passed in 1.49s** (100% pass rate).
   - Running `.venv/bin/pytest tests/unit/test_tokenizer.py` showed **12 passed in 0.09s**.

---

## 2. Logic Chain

1. **Root Cause of Left-to-Right Year Failure**:
   `RE_YEAR.search(stem)` in `tokenizer.py:235` scans left-to-right. For movies with numerical titles (`1917`, `2001`, `2049`, `1984`, `1999`), the title digits match first, stripping the title and setting an erroneous release year.
2. **Right-to-Left Delimiter Boundary Reasoning**:
   In standard scene releases, technical specifications (`1080p`, `BluRay`, `x264`, `Extended`, `Remastered`) always appear *after* the release year. By detecting the start of technical specs (`tech_start`) and selecting the rightmost candidate matching `(?<![0-9a-zA-Z])(19\d{2}|20\d{2})(?![0-9a-zA-Z])` before `tech_start`, the release year is cleanly isolated from preceding numerical title tokens.
3. **Regex Precedence & Conflict Resolution**:
   In the baseline, `RE_ANIME_RELEASE` executed before `RE_SEASON_EPISODE`. Because `RE_ANIME_RELEASE` permitted hyphens before numbers (`\s*-\s*\d+`), it captured `2x01-02` as anime episode 02. Reordering TV episodic check *before* anime fansub check resolves `TV-05` without breaking any anime patterns.
4. **Data Structure Completeness**:
   Adding `edition`, `part`, `part_label`, `air_date`, `is_daily`, and `is_season_pack` to `TokenizedFilename` with default values (`None` / `False`) preserves 100% backward compatibility with existing callers while providing all necessary metadata for `classifier.py` and `namer.py`.
5. **Empirical Prototype Proof**:
   The prototype implementation (`EnhancedTokenizer`) in `.agents/teamwork_preview_explorer_m2_1/test_enhanced_prototype.py` was tested against all 64 benchmark cases. It achieved **64 / 64 token accuracy (0 mismatches)** and passed all 12 existing tokenizer unit tests without regression.

---

## 3. Caveats

1. **Downstream Classifier Adjustments**:
   While the tokenizer provides 100% accurate tokens, full benchmark execution requires minor downstream adjustments in `classifier.py` (specifically awarding podcast confidence to dated audio files in `DAILY-05`/`DAILY-09`, and bypassing the `dur < 900` check for reserved device names in `MESSY-08`).
2. **Template Renaming Dependency (Milestone M3)**:
   Destination subpaths in `namer.py` and `config.py` require standardizing the TV template separator from `_` to ` - ` (e.g. `Show - S01E01.mkv`), handling Season 0 falsy checks, and appending ` [edition]` / ` [part_label]`. These are scheduled for M2/M3 builder implementation.
3. **Known Anime Franchise List**:
   The tokenizer prototype uses a small set of known anime titles (`naruto`, `bleach`, etc.) to distinguish standalone episode anime keywords from standard TV shows.

---

## 4. Conclusion

The tokenizer enhancements are fully investigated, specified, and empirically proven.
- `src/media_sorter/tokenizer.py` can be upgraded with exact line-by-line regexes and parsing order documented in Section 3 of `analysis.md`.
- Resolves all 27 tokenizer benchmark failures across ambiguous numerical years, TV Roman numerals, multi-episode ranges, season packs, movie editions, split parts, daily broadcast TV, and messy filenames.
- Eliminates 12 out of 15 category mismatches in `classifier.py` automatically.
- Maintains 100% backward compatibility with existing unit tests and REST API facades.

---

## 5. Verification Method

To independently verify the findings and prototype:
1. **Run Prototype Benchmark Evaluation (0 mismatches)**:
   ```bash
   .venv/bin/python .agents/teamwork_preview_explorer_m2_1/test_enhanced_prototype.py
   ```
   *Expected output*: `Remaining token mismatches: 0 / 64`.
2. **Run Existing Tokenizer Unit Tests Against Prototype (100% pass)**:
   ```bash
   .venv/bin/python .agents/teamwork_preview_explorer_m2_1/test_existing_unit_tests.py
   ```
   *Expected output*: `ALL 12 EXISTING UNIT TESTS PASSED WITH ENHANCED TOKENIZER!`.
3. **Run Existing Baseline Unit and Integration Tests**:
   ```bash
   .venv/bin/pytest tests/unit/ tests/integration/
   ```
   *Expected output*: `83 passed`.
4. **Inspect Detailed Analysis Report**:
   Read `/md0/media-sorter/.agents/teamwork_preview_explorer_m2_1/analysis.md`.
