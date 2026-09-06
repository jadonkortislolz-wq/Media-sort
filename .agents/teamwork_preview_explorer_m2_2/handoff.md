# Handoff Report: Media Classification & Standardized Destination Naming Investigation

**Agent**: `teamwork_preview_explorer_m2_2`  
**Working Directory**: `/md0/media-sorter/.agents/teamwork_preview_explorer_m2_2`  
**Analysis Reference**: `/md0/media-sorter/.agents/teamwork_preview_explorer_m2_2/analysis.md`  
**Date**: 2026-09-06  

---

### 1. Observation

1. **Test Baseline Measurements**:
   - Running `.venv/bin/pytest tests/unit/ tests/integration/` produces **83 passed in 1.52s** (100% pass rate).
   - Running `.venv/bin/python tests/benchmark/runner.py --no-diffs` outputs:
     `Total Cases: 64 | Passed: 1 | Failed: 63 | Pass Rate: 1.6% | Total Duration: 127.1ms`.
   - The single passing test is `MESSY-06` (`The.Dark.Knight.2008.1080p.forced.srt`).

2. **Season 00 & Episode 00 Falsy Bug**:
   - In `src/media_sorter/namer.py:164-166`:
     ```python
     season_num = (tokens.season if tokens else 1) or 1
     episode_num = (tokens.episode if tokens else 1) or 1
     season_ep_str = f"S{season_num:02d}E{episode_num:02d}"
     ```
   - For `SPECIAL-01` (`The.Office.S00E01...`): `tokens.season = 0`. In Python: `0 or 1 == 1`.
     Destination generated: `TV Shows/The Office/Season 01/The Office_S01E01.mkv`.
     Expected: `TV Shows/The Office/Season 00/The Office - S00E01.mkv`.
   - For `SPECIAL-03` (`Breaking.Bad.S05E00...`): `tokens.episode = 0`. In Python: `0 or 1 == 1`.
     Destination generated: `Breaking Bad_S05E01.mkv`.
     Expected: `Breaking Bad - S05E00.mkv`.

3. **Daily TV vs Movie Misclassification**:
   - In `src/media_sorter/classifier.py:313-320`:
     ```python
     is_tv = False
     if tokens.is_episodic:
         is_tv = True
     ```
     Daily TV shows (`DAILY-01` to `DAILY-08`) contain calendar air dates (e.g. `2024-01-15`, `2024.03.12`), but lack `SxxExx` episode numbers. `tokens.is_episodic` is `False`.
   - In `classifier.py:364-370`:
     `movie_score = 0.40` + `0.35` (`tokens.year == 2024`) + `0.15` (`1080p/HDTV`) = `0.90`.
     Because `0.90 >= 0.75`, `DAILY-01` through `DAILY-08` are classified as `movie` (`Movies/The Daily Show (2024)/The Daily Show.mkv`).

4. **Dated Podcast Misclassification**:
   - In `src/media_sorter/classifier.py:194-206`:
     `DAILY-05` (`The Daily - 2026-03-12 - The Sunday Read.mp3`) and `DAILY-09` (`NPR.News.Now.2024-06-10.mp3`) lack folder hints and ID3 tags.
     `pod_score` receives only `+0.35` for `tokens.date_stamp`.
     `0.35 < 0.60` (the required podcast threshold), so it falls through to `music` (`confidence 0.50`), getting quarantined as `"Audio file lacking track/artist metadata"`.

5. **Anime Formatting & Release Group Defect**:
   - In `src/media_sorter/namer.py:187`:
     `"group": (tokens.group if tokens else "UnknownGroup") or "UnknownGroup"`
   - For `ANIME-09` (`BLEACH - Sennen Kessen-hen - 27 [E89717B7].mkv`), destination emitted:
     `Anime/BLEACH - Sennen Kessen-hen/Season 01/BLEACH - Sennen Kessen-hen_S01E27 [UnknownGroup].mkv`.
     Expected: `Anime/BLEACH - Sennen Kessen-hen/BLEACH - Sennen Kessen-hen - 27.mkv`.
   - For all anime cases, `Season 01/` subdirectories and `_S01Exx` episode formatting were inserted despite fansub standards requiring flat show directories with absolute numbering.

6. **Movie Editions, Multi-Part, and Extras Formatting**:
   - In `src/media_sorter/config.py:120`: `movie: str = "{title} ({year})/{movie_name}.{ext}"`.
   - `MOVIE-01` (`Inception.2010...`): Emitted `Movies/Inception (2010)/Inception.mkv` (missing year in filename).
   - `MOVIE-07` / `MOVIE-08` (`Titanic.1997.DVD.CD1.avi` / `CD2.avi`): Both emitted `Movies/Titanic (1997)/Titanic.avi` (collision).
   - `SPECIAL-04` through `SPECIAL-07` (`Inception.2010-behindthescenes.mkv`, etc.): Suffix stripped, emitted `Movies/Inception (2010)/Inception.mkv` (overwriting movie).

---

### 2. Logic Chain

1. **From Observation 2 to Season 00 Fix**:
   - Because `(tokens.season or 1)` coerces `0` to `1`, replacing with `season_num = tokens.season if (tokens and tokens.season is not None) else 1` guarantees that `tokens.season = 0` evaluates to `0`.
   - When formatted into `f"Season {season_num:02d}"` and `f"S{season_num:02d}"`, this directly yields `Season 00` and `S00E01` (resolving `SPECIAL-01`, `02`, `08`, `09`).
   - Similarly, checking `tokens.episode is not None` ensures Episode 0 specials (`S05E00`) remain `E00` (resolving `SPECIAL-03`).

2. **From Observation 3 to Daily TV Routing**:
   - Because daily TV broadcasts have a full calendar date (`YYYY-MM-DD`, `YYYY.MM.DD`, `YYYY_MM_DD`) in stem or `tokens.date_stamp`, checking `RE_BROADCAST_DATE` in `_classify_video` allows setting `is_tv = True` with `+0.45` confidence boost.
   - Concurrently, suppressing `movie_score += 0.35` when a calendar broadcast date is present prevents daily shows from achieving movie threshold (resolving `DAILY-01`, `02`, `03`, `04`, `06`, `07`, `08`).
   - In `MediaNamer`, routing TV shows with dates to `{show_name}/Season {year}/{show_name} - {date}.{ext}` generates the exact expected subpaths.

3. **From Observation 4 to Podcast Calibration**:
   - Audio files containing a calendar date stamp without music track numbering (`tokens.track is None` and not `tokens.is_music`) are distinctively episodic podcasts.
   - Awarding `+0.45` for date stamp and `+0.30` for non-music audio raises `pod_score` to `0.75 >= 0.60`, classifying as `podcast` with confidence ≥ 0.75 and eliminating false quarantine (resolving `DAILY-05` and `DAILY-09`).

4. **From Observation 5 to Anime Routing & Naming**:
   - In `MediaNamer`:
     a) Removing `Season 01/` folder for anime and routing flatly as `Anime/{title}/{title} - {episode}{group_tag}.ext`.
     b) Setting `group_tag = f" [{tokens.group}]"` only when `tokens.group` is known and not empty / "UnknownGroup", and `""` otherwise, eliminates `[UnknownGroup]`.
     c) Supporting anime multi-episode range (`01-02`).
   - In `MediaClassifier`:
     a) Recognizing known anime fansub groups (`[SubsPlease]`, `[HorribleSubs]`, `[Judas]`, `[TaigaSubs]`, `[Erai-raws]`), CRC32 hashes (`\[[0-9A-Fa-f]{8}\]`), OVA tags, and standalone `Episode <number>`.
     b) Guarding against scene groups (`[rartv]`, `[YTS.MX]`) and standard TV episodes (`2x01-02`).
   - This resolves `ANIME-01` through `ANIME-11`, `TV-05`, `MESSY-03`, and `MESSY-05`.

5. **From Observation 6 to Movie & Extras Formatting**:
   - Structuring movie destination formatting as `{title} ({year})/{title} ({year}) [Edition] [Pt.X]{extra_suffix}.ext`:
     a) Preserves year in filename (`Inception (2010).mkv`).
     b) Renders edition tags (`[Remastered]`, `[Extended]`, `[Director's Cut]`, `[Criterion]`, `[Final Cut]`).
     c) Renders multi-part markers (`[Pt.1]`, `[Pt.2]`), preventing overwrite collisions.
     d) Preserves extras suffixes (`-behindthescenes`, `-deleted`, `-trailer`, `-featurette`).
   - This resolves `MOVIE-01` through `MOVIE-14` and `SPECIAL-04` through `SPECIAL-07`.

6. **From Empirical Simulation to Zero Regressions**:
   - Running the combined classification and destination rendering rules against all 64 benchmark cases verified **0/64 mismatches** (100% pass rate).
   - Checking the 83 existing unit and integration tests confirmed that none of the assertions are violated by the improved formats (e.g. `test_generate_tv_destination` checks `"Season 01" in str(dest)`, `"Breaking Bad" in str(dest)`, `"S01E01" in str(dest)` — all remain true).

---

### 3. Caveats

1. **Upstream Tokenizer Dependencies**: Full end-to-end benchmark execution in `test_benchmark.py` also tests tokenizer extraction of `tokens.edition`, `tokens.part`, `tokens.air_date`, and Roman numerals. The design in `namer.py` and `classifier.py` incorporates regex fallbacks so that classification and naming succeed even if `TokenizedFilename` fields have not yet been populated by the tokenizer.
2. **Library Indexing Sync**: In `sorter.py:274`, anime indexing requires using `settings.get_destination_path("anime")` instead of `shows_dir` to prevent `ValueError: path is not in subpath`.
3. **External Network Providers**: All tests and benchmarks run 100% offline with `provider=None`. If TMDB online metadata is enabled in production, provider confidence boosts integrate cleanly with the calibrated scoring matrix.

---

### 4. Conclusion

- Media classification and destination naming have been comprehensively diagnosed. The 63 benchmark failures stem from identifiable, fixable logic gaps in `classifier.py` and `namer.py`.
- The Season 00 falsy bug in `namer.py:164-165` is fully solved by replacing boolean `or` with `is not None` null checking.
- Standard TV destination template formatting must be standardized to `{show_name}/Season {season:02d}/{show_name} - {season_episode}.{ext}` with multi-episode support (`S04E01-E02`) and season pack support (`Season 02`).
- Anime destination formatting must route to `Anime/{title}/{title} - {episode} [{group}].ext`, omit `[UnknownGroup]`, and recognize absolute numbering, cour tags, OVA specials, and standalone `Episode` keywords.
- Daily TV shows must be classified as `tv` and formatted as `TV Shows/{show_name}/Season {year}/{show_name} - {date}.ext`.
- Movie destinations must format as `Movies/{title} ({year})/{title} ({year}) [Edition] [Pt.X].ext` while preserving behind-the-scenes and extras suffixes (`-behindthescenes`, etc.).
- Complete implementation code, before/after snippets, and mathematical scoring calibrations are documented in detail in `analysis.md`.

---

### 5. Verification Method

1. **Verify Baseline Unit & Integration Tests (83 tests)**:
   ```bash
   .venv/bin/pytest tests/unit/ tests/integration/
   ```
   *Expected Result*: 83 passed in ~1.5s with zero failures.

2. **Verify Benchmark Runner Execution**:
   ```bash
   .venv/bin/python -m tests.benchmark.runner --no-diffs
   ```
   *Baseline*: 1 passed, 63 failed.
   *Target after applying proposed enhancements*: 64 passed, 0 failed (100% pass rate).

3. **Verify Pure-Memory Simulation of Proposed Enhancements**:
   Run the simulation script embedded in `analysis.md` across all 64 benchmark cases:
   ```bash
   .venv/bin/python -c "
   from tests.benchmark.benchmark_cases import BENCHMARK_CASES
   # (Execute the verification snippet in Section 4 of analysis.md)
   "
   ```
   *Expected Result*: `SUCCESS: All 64 benchmark destination paths generated identically! (0 mismatches)`.

4. **Invalidation Conditions**:
   - Any regression in the 83 existing unit/integration tests invalidates the proposed calibration.
   - Any destination path containing `[UnknownGroup]` or `Season 01/` for anime invalidates the naming design.
   - Any daily broadcast TV show classified as `movie` invalidates the classification heuristics.
