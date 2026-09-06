# Media Sorter E2E Benchmark Test Suite & Offline Runner (TEST_READY)

**Milestone**: E2E Benchmark Suite (Requirement R2 / Feature F13)  
**Date**: 2026-09-05  
**Working Directory**: `/md0/media-sorter`  
**Test Location**: `tests/benchmark/`  
**Status**: COMPLETE & VERIFIED  

---

## 1. Executive Summary

Requirement R2 requires developing a repeatable, isolated automated verification suite testing filename tokenization, media classification, and destination path resolution against a diverse benchmark dataset of real-world media filename patterns.

The E2E Benchmark Test Suite and Offline Diagnostic Runner have been established:
- **Test Inventory**: 64 real-world media filename patterns spanning 6 distinct domains.
- **Pure In-Memory Offline Execution**: Operates with 0 external network requests, 0 filesystem mutations, and zero risk to host media storage (`/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`).
- **Execution Performance**: Full 64-case suite executes in ~107 milliseconds.
- **Diagnostic Transparency**: Field-by-field diff reporting across category, title, year, season, episode, multi-episodes, date, edition, part, group, and destination subpath.
- **Zero Regressions**: All 82 existing unit, integration, safety, and defect tests continue to pass with a 100% pass rate.

---

## 2. Test Runner Invocation Commands

### 2.1 Pytest Benchmark Runner
Executes the parametrized pytest test suite (`@pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c.id)`):
```bash
.venv/bin/pytest tests/benchmark/test_benchmark.py
```
To run specific domains or cases:
```bash
.venv/bin/pytest tests/benchmark/test_benchmark.py -k "TV"
.venv/bin/pytest tests/benchmark/test_benchmark.py -k "ANIME"
.venv/bin/pytest tests/benchmark/test_benchmark.py -k "MOVIE"
```

### 2.2 Standalone CLI Benchmark Runner
Executes the offline benchmark runner with Rich terminal formatting and JSON export:
```bash
.venv/bin/python -m tests.benchmark.runner
```
Or directly:
```bash
.venv/bin/python tests/benchmark/runner.py
```

#### Supported CLI Options:
| Flag | Description | Example |
|---|---|---|
| `--domain <domain>` | Filter execution to a single domain | `.venv/bin/python -m tests.benchmark.runner --domain Anime` |
| `--case <case_id>` | Filter execution to a single benchmark case | `.venv/bin/python -m tests.benchmark.runner --case TV-01` |
| `--json-output <path>` | Custom path for exported summary JSON | `--json-output custom_summary.json` |
| `--no-diffs` | Print summary table only without failure diffs | `--no-diffs` |
| `--verbose`, `-v` | Display output for all cases (including passed) | `-v` |
| `--strict` | Exit with status code 1 if any case fails | `--strict` |

### 2.3 Existing Regression Test Suite
Verify that all unit and integration tests remain intact:
```bash
.venv/bin/pytest tests/unit/ tests/integration/
```
Result: **82 passed in ~1.67s** (100% pass rate).

---

## 3. Benchmark Domain Coverage Matrix (64 Cases)

The benchmark inventory defines authoritative ground truth for 64 real-world patterns across 6 domains:

### Domain 1: Standard TV (11 Cases)
| ID | Filename | Edge Case Type | Expected Category | Expected Season/Episode | Expected Destination Subpath | Baseline Status |
|---|---|---|---|---|---|---|
| `TV-01` | `Breaking.Bad.S05E14.Ozymandias.1080p.BluRay.x264-ROVERS.mkv` | Standard SxxExx | tv | S05E14 | `TV Shows/Breaking Bad/Season 05/Breaking Bad - S05E14.mkv` | Pending M3 format (`_` vs ` - `) |
| `TV-02` | `Stranger.Things.S04E01-E02.Chapter.One.720p.WEB-DL.mkv` | Multi-ep hyphen range | tv | S04E01-E02 | `TV Shows/Stranger Things/Season 04/Stranger Things - S04E01-E02.mkv` | Pending M2 multi-ep & M3 format |
| `TV-03` | `House.M.D.S03E01E02.1080p.mkv` | Concatenated multi-ep | tv | S03E01-E02 | `TV Shows/House M D/Season 03/House M D - S03E01-E02.mkv` | Pending M2 multi-ep & M3 format |
| `TV-04` | `The.Wire.1x09.HDTV.mkv` | Scene 1x09 | tv | S01E09 | `TV Shows/The Wire/Season 01/The Wire - S01E09.mkv` | Pending M3 format (`_` vs ` - `) |
| `TV-05` | `The.Office.2x01-02.mkv` | Scene multi-ep range | tv | S02E01-E02 | `TV Shows/The Office/Season 02/The Office - S02E01-E02.mkv` | Pending M2 multi-ep disambiguation |
| `TV-06` | `Rome.Season.II.Episode.IV.mkv` | Roman numerals | tv | S02E04 | `TV Shows/Rome/Season 02/Rome - S02E04.mkv` | Pending M2 Roman numeral parser |
| `TV-07` | `Doctor Who Season 5 Episode 1 Eleventh Hour.mkv` | Word season & episode | tv | S05E01 | `TV Shows/Doctor Who/Season 05/Doctor Who - S05E01.mkv` | Pending M3 format (`_` vs ` - `) |
| `TV-08` | `Succession.S02.Complete.1080p.WEB-DL.mkv` | Complete season pack | tv | S02 (Pack) | `TV Shows/Succession/Season 02/Succession - Season 02.mkv` | Pending M2 season pack tokenizer |
| `TV-09` | `Game.of.Thrones.S08E03.720p.HDTV.x264-AVS.mkv` | Scene release group | tv | S08E03 | `TV Shows/Game of Thrones/Season 08/Game of Thrones - S08E03.mkv` | Pending M3 format (`_` vs ` - `) |
| `TV-10` | `Chernobyl.S01E05.Vichnaya.Pamyat.1080p.mkv` | Episode title in stem | tv | S01E05 | `TV Shows/Chernobyl/Season 01/Chernobyl - S01E05.mkv` | Pending M3 format (`_` vs ` - `) |
| `TV-11` | `Friends.S06E15-E16.The.One.That.Could.Have.Been.mkv` | Double-digit multi-ep | tv | S06E15-E16 | `TV Shows/Friends/Season 06/Friends - S06E15-E16.mkv` | Pending M2 multi-ep & M3 format |

### Domain 2: Anime (11 Cases)
| ID | Filename | Edge Case Type | Expected Category | Expected Episode / Group | Expected Destination Subpath | Baseline Status |
|---|---|---|---|---|---|---|
| `ANIME-01` | `[SubsPlease] Frieren - Beyond Journey's End - 01 (1080p) [ABCD1234].mkv` | Fansub brackets & CRC | anime | Ep 01 / SubsPlease | `Anime/Frieren - Beyond Journey's End/Frieren - Beyond Journey's End - 01 [SubsPlease].mkv` | Pending M3 Anime destination routing |
| `ANIME-02` | `[SubsPlease] 葬送のフリーレン - 12 (1080p) [98E7B1A2].mkv` | Unicode / Kanji title | anime | Ep 12 / SubsPlease | `Anime/葬送のフリーレン/葬送のフリーレン - 12 [SubsPlease].mkv` | Pending M3 Anime destination routing |
| `ANIME-03` | `[HorribleSubs] Fairy Tail (2014) - 176 [720p].mkv` | Parenthesized title year | anime | Ep 176 / HorribleSubs | `Anime/Fairy Tail (2014)/Fairy Tail (2014) - 176 [HorribleSubs].mkv` | Pending M2 Anime parenthesized title |
| `ANIME-04` | `[Erai-raws] One Piece - 1088 [1080p].mkv` | 4-digit absolute numbering | anime | Ep 1088 / Erai-raws | `Anime/One Piece/One Piece - 1088 [Erai-raws].mkv` | Pending M2 absolute number routing |
| `ANIME-05` | `[SubsPlease] Dungeon Meshi - 01-02 (1080p).mkv` | Anime multi-episode range | anime | Ep 01-02 / SubsPlease | `Anime/Dungeon Meshi/Dungeon Meshi - 01-02 [SubsPlease].mkv` | Pending M2 multi-ep anime |
| `ANIME-06` | `[TaigaSubs] Attack on Titan OVA - 01 [720p].mkv` | Anime OVA special | anime | Ep 01 / TaigaSubs | `Anime/Attack on Titan OVA/Attack on Titan OVA - 01 [TaigaSubs].mkv` | Pending M2 OVA parser |
| `ANIME-07` | `Naruto Episode 207 The Supposed Sealed Ability.mkv` | Standalone episode keyword | anime | Ep 207 | `Anime/Naruto/Naruto - 207.mkv` | Pending M2 anime keyword classification |
| `ANIME-08` | `[Judas] Fate Stay Night - Heaven's Feel - I. Presage Flower [BD 1080p].mkv` | Roman numeral sub-title | anime | Movie / Judas | `Anime/Fate Stay Night - Heaven's Feel - I. Presage Flower/...` | Pending M2 Roman numeral & anime routing |
| `ANIME-09` | `BLEACH - Sennen Kessen-hen - 27 [E89717B7].mkv` | No-group fansub with CRC | anime | Ep 27 | `Anime/BLEACH - Sennen Kessen-hen/BLEACH - Sennen Kessen-hen - 27.mkv` | Pending M2 fansub syntax & M3 routing |
| `ANIME-10` | `[Erai-raws] Jujutsu Kaisen 2nd Season - 14 [1080p][Multiple Subtitle].mkv` | Cour / season tags | anime | Ep 14 / Erai-raws | `Anime/Jujutsu Kaisen 2nd Season/Jujutsu Kaisen 2nd Season - 14 [Erai-raws].mkv` | Pending M2 cour pattern |
| `ANIME-11` | `[SubsPlease] Mushoku Tensei S2 - 18 (1080p) [F28B1452].mkv` | Short season notation S2 | anime | Ep 18 / SubsPlease | `Anime/Mushoku Tensei S2/Mushoku Tensei S2 - 18 [SubsPlease].mkv` | Pending M2 S2 anime tokenizer |

### Domain 3: Movies (14 Cases)
| ID | Filename | Edge Case Type | Expected Category | Expected Year / Edition / Part | Expected Destination Subpath | Baseline Status |
|---|---|---|---|---|---|---|
| `MOVIE-01` | `Inception.2010.1080p.BluRay.x264-FraMeSToR.mkv` | Standard release year | movie | 2010 | `Movies/Inception (2010)/Inception (2010).mkv` | Pending M3 movie template name |
| `MOVIE-02` | `1917.2019.1080p.BluRay.x264.mkv` | Numerical title with year | movie | 2019 (Title: 1917) | `Movies/1917 (2019)/1917 (2019).mkv` | Pending M2 year disambiguation |
| `MOVIE-03` | `2001.A.Space.Odyssey.1968.REMASTERED.1080p.mkv` | Numerical title & edition | movie | 1968 / Remastered | `Movies/2001 A Space Odyssey (1968)/... [Remastered].mkv` | Pending M2 numerical title & edition |
| `MOVIE-04` | `Blade.Runner.2049.2017.2160p.UHD.BluRay.x265.mkv` | Future year in title | movie | 2017 (Title: Blade Runner 2049) | `Movies/Blade Runner 2049 (2017)/...` | Pending M2 year disambiguation |
| `MOVIE-05` | `Wonder.Woman.1984.2020.1080p.WEB-DL.mkv` | Year in title | movie | 2020 (Title: Wonder Woman 1984) | `Movies/Wonder Woman 1984 (2020)/...` | Pending M2 year disambiguation |
| `MOVIE-06` | `Class.of.1999.1990.720p.mkv` | Past year in title | movie | 1990 (Title: Class of 1999) | `Movies/Class of 1999 (1990)/...` | Pending M2 year disambiguation |
| `MOVIE-07` | `Titanic.1997.DVD.CD1.avi` | Multi-part movie CD1 | movie | 1997 / Part 1 | `Movies/Titanic (1997)/Titanic (1997) [Pt.1].avi` | Pending M2 part parser & M3 path |
| `MOVIE-08` | `Titanic.1997.DVD.CD2.avi` | Multi-part movie CD2 | movie | 1997 / Part 2 | `Movies/Titanic (1997)/Titanic (1997) [Pt.2].avi` | Pending M2 part parser & M3 path |
| `MOVIE-09` | `Kill.Bill.Vol.1.2003.1080p.BluRay.mkv` | Volume number in title | movie | 2003 (Title: Kill Bill Vol 1) | `Movies/Kill Bill Vol 1 (2003)/...` | Pending M3 movie template name |
| `MOVIE-10` | `The.Lord.of.the.Rings.The.Fellowship.of.the.Ring.2001.Extended.1080p.mkv` | Extended edition | movie | 2001 / Extended | `Movies/The Lord of the Rings... [Extended].mkv` | Pending M2 edition parser |
| `MOVIE-11` | `Aliens.1986.Directors.Cut.1080p.BluRay.mkv` | Director's Cut edition | movie | 1986 / Director's Cut | `Movies/Aliens (1986)/Aliens (1986) [Director's Cut].mkv` | Pending M2 edition parser |
| `MOVIE-12` | `Gladiator.2000.Remastered.1080p.BluRay.mkv` | Remastered edition | movie | 2000 / Remastered | `Movies/Gladiator (2000)/Gladiator (2000) [Remastered].mkv` | Pending M2 edition parser |
| `MOVIE-13` | `Seven.Samurai.1954.Criterion.Collection.1080p.BluRay.mkv` | Criterion edition | movie | 1954 / Criterion | `Movies/Seven Samurai (1954)/Seven Samurai (1954) [Criterion].mkv` | Pending M2 edition parser |
| `MOVIE-14` | `Blade.Runner.1982.Final.Cut.2160p.UHD.mkv` | Final Cut edition | movie | 1982 / Final Cut | `Movies/Blade Runner (1982)/Blade Runner (1982) [Final Cut].mkv` | Pending M2 edition parser |

### Domain 4: Specials & Extras (9 Cases)
| ID | Filename | Edge Case Type | Expected Category | Expected Season/Episode | Expected Destination Subpath | Baseline Status |
|---|---|---|---|---|---|---|
| `SPECIAL-01` | `The.Office.S00E01.The.Outtakes.mkv` | Season 00 TV special | tv | S00E01 | `TV Shows/The Office/Season 00/The Office - S00E01.mkv` | Pending M3 Season 00 falsy bug fix |
| `SPECIAL-02` | `Doctor.Who.S00E25.The.Day.of.the.Doctor.1080p.mkv` | High episode Season 00 | tv | S00E25 | `TV Shows/Doctor Who/Season 00/Doctor Who - S00E25.mkv` | Pending M3 Season 00 falsy bug fix |
| `SPECIAL-03` | `Breaking.Bad.S05E00.Special.mkv` | Mid-season special E00 | tv | S05E00 | `TV Shows/Breaking Bad/Season 05/Breaking Bad - S05E00.mkv` | Pending M3 Season 00 falsy bug fix |
| `SPECIAL-04` | `Inception.2010-behindthescenes.mkv` | Behind the scenes extra | movie | 2010 | `Movies/Inception (2010)/Inception (2010)-behindthescenes.mkv` | Pending M3 extra suffix preservation |
| `SPECIAL-05` | `The.Matrix.1999-featurette.mkv` | Movie featurette extra | movie | 1999 | `Movies/The Matrix (1999)/The Matrix (1999)-featurette.mkv` | Pending M3 extra suffix preservation |
| `SPECIAL-06` | `Interstellar.2014-deleted.mkv` | Deleted scenes extra | movie | 2014 | `Movies/Interstellar (2014)/Interstellar (2014)-deleted.mkv` | Pending M3 extra suffix preservation |
| `SPECIAL-07` | `Interstellar.2014-trailer.mp4` | Movie trailer extra | movie | 2014 | `Movies/Interstellar (2014)/Interstellar (2014)-trailer.mp4` | Pending M3 extra suffix preservation |
| `SPECIAL-08` | `Game.of.Thrones.S00E02.A.Day.in.the.Life.mkv` | Season 00 with title | tv | S00E02 | `TV Shows/Game of Thrones/Season 00/Game of Thrones - S00E02.mkv` | Pending M3 Season 00 falsy bug fix |
| `SPECIAL-09` | `Sherlock.S00E01.Many.Happy.Returns.mkv` | TV special prequel | tv | S00E01 | `TV Shows/Sherlock/Season 00/Sherlock - S00E01.mkv` | Pending M3 Season 00 falsy bug fix |

### Domain 5: Daily / Dated Shows (9 Cases)
| ID | Filename | Edge Case Type | Expected Category | Expected Date | Expected Destination Subpath | Baseline Status |
|---|---|---|---|---|---|---|
| `DAILY-01` | `The.Daily.Show.2024-01-15.1080p.HDTV.mkv` | ISO dated TV | tv | 2024-01-15 | `TV Shows/The Daily Show/Season 2024/The Daily Show - 2024-01-15.mkv` | Pending M2 daily regex & M3 TV routing |
| `DAILY-02` | `The.Tonight.Show.Starring.Jimmy.Fallon.2024.03.12.720p.mkv` | Dot-dated TV | tv | 2024-03-12 | `TV Shows/The Tonight Show.../Season 2024/... - 2024-03-12.mkv` | Pending M2 daily regex & M3 TV routing |
| `DAILY-03` | `Last.Week.Tonight.with.John.Oliver.2023-11-05.1080p.mkv` | Weekly dated show | tv | 2023-11-05 | `TV Shows/Last Week Tonight.../Season 2023/... - 2023-11-05.mkv` | Pending M2 daily regex & M3 TV routing |
| `DAILY-04` | `Late.Night.with.Seth.Meyers.2024_02_20.720p.mkv` | Underscore dated TV | tv | 2024-02-20 | `TV Shows/Late Night.../Season 2024/... - 2024-02-20.mkv` | Pending M2 daily regex & M3 TV routing |
| `DAILY-05` | `The Daily - 2026-03-12 - The Sunday Read.mp3` | Dated podcast | podcast | 2026-03-12 | `Podcasts/The Daily/2026/The Daily - 2026-03-12 - The Sunday Read.mp3` | Pending M2 podcast date & classifier |
| `DAILY-06` | `Jimmy.Kimmel.Live.2024-04-18.720p.HDTV.mkv` | Daily show ISO | tv | 2024-04-18 | `TV Shows/Jimmy Kimmel Live/Season 2024/Jimmy Kimmel Live - 2024-04-18.mkv` | Pending M2 daily regex & M3 TV routing |
| `DAILY-07` | `PBS.NewsHour.2024.05.01.720p.mkv` | News dot date | tv | 2024-05-01 | `TV Shows/PBS NewsHour/Season 2024/PBS NewsHour - 2024-05-01.mkv` | Pending M2 daily regex & M3 TV routing |
| `DAILY-08` | `The.Late.Show.with.Stephen.Colbert.2024-02-14.1080p.mkv` | Late night show ISO | tv | 2024-02-14 | `TV Shows/The Late Show.../Season 2024/... - 2024-02-14.mkv` | Pending M2 daily regex & M3 TV routing |
| `DAILY-09` | `NPR.News.Now.2024-06-10.mp3` | Podcast daily news | podcast | 2024-06-10 | `Podcasts/NPR News Now/2024/NPR News Now - 2024-06-10.mp3` | Pending M2 podcast date & classifier |

### Domain 6: Messy & Complex (10 Cases)
| ID | Filename | Edge Case Type | Expected Category | Expected Attributes | Expected Destination Subpath | Baseline Status |
|---|---|---|---|---|---|---|
| `MESSY-01` | `Amélie.2001.PROPER.REMASTERED.1080p.BluRay.x264-CiNEFiLE.mkv` | Accented characters | movie | 2001 / Remastered / CiNEFiLE | `Movies/Amélie (2001)/Amélie (2001) [Remastered].mkv` | Pending M2 edition & M3 template |
| `MESSY-02` | `Wolfs.2024.1080p.Apple.TV.WEB-DL.DDP5.1.Atmos.H.264.mkv` | Apple TV scene tag | movie | 2024 | `Movies/Wolfs (2024)/Wolfs (2024).mkv` | Pending M2 Apple.TV spec stripping |
| `MESSY-03` | `Gladiator.II.2024.1080p.HDTV.x264-[rartv].mkv` | Roman numeral title | movie | 2024 / rartv | `Movies/Gladiator II (2024)/Gladiator II (2024).mkv` | Pending M2 bracket group parsing |
| `MESSY-04` | `Interstellar.1920x1080.mkv` | Resolution dimensions | movie | Title: Interstellar | `Movies/Interstellar/Interstellar.mkv` | Pending M2 dimension stripping & quarantine |
| `MESSY-05` | `[YTS.MX] Movie Title - 2024 [1080p].mkv` | Bracket movie group | movie | 2024 / YTS.MX | `Movies/Movie Title (2024)/Movie Title (2024).mkv` | Pending M2 bracket group non-anime |
| `MESSY-06` | `The.Dark.Knight.2008.1080p.forced.srt` | Subtitle forced tag | subtitle | 2008 / Subtitle | `Movies/The Dark Knight (2008)/The Dark Knight (2008).forced.srt` | **PASSED** (100% match) |
| `MESSY-07` | `Show: "Special" <Episode> \| 1?.mkv` | Forbidden characters | tv | Ep 1 / Sanitized | `TV Shows/Show Special Episode 1/Season 01/... - S01E01.mkv` | Pending M2 character sanitization |
| `MESSY-08` | `CON.mp4` | Windows reserved device | home_video | CON -> _CON | `Home Videos/2026/2026-01 - Event/_CON.mp4` | Pending M2 reserved name handling |
| `MESSY-09` | `  Messy  Show . S01E01 .  1080p .mkv` | Whitespace & dot padding | tv | S01E01 | `TV Shows/Messy Show/Season 01/Messy Show - S01E01.mkv` | Pending M2 whitespace collapse |
| `MESSY-10` | `Show_Name__2022__S02E03__HDTV.mkv` | Consecutive underscores | tv | 2022 / S02E03 | `TV Shows/Show Name/Season 02/Show Name - S02E03.mkv` | Pending M2 underscore normalization |

---

## 4. Initial Pass/Fail Baseline Report

### 4.1 Empirical Baseline Summary Table
Measured against codebase at commit baseline (`M0 / Phase 0`) prior to M2/M3 implementation:

| Domain | Total Cases | Passed | Failed | Pass Rate (%) | Avg Duration |
|---|---|---|---|---|---|
| **Standard TV** | 11 | 0 | 11 | 0.0% | 1.75 ms |
| **Anime** | 11 | 0 | 11 | 0.0% | 1.66 ms |
| **Movies** | 14 | 0 | 14 | 0.0% | 1.66 ms |
| **Specials & Extras** | 9 | 0 | 9 | 0.0% | 1.65 ms |
| **Daily / Dated Shows** | 9 | 0 | 9 | 0.0% | 1.65 ms |
| **Messy & Complex** | 10 | 1 | 9 | 10.0% | 1.65 ms |
| **OVERALL** | **64** | **1** | **63** | **1.6%** | **106.9 ms total** |

### 4.2 Gap Classification & Milestone Resolution Roadmap

The 63 baseline test failures cleanly delineate the exact functional requirements scheduled for Milestones M2 and M3:

#### Gap Group 1: Numerical Title & Year Ambiguity (M2: Feature F3)
- **Observed Defect**: `RE_YEAR` searches left-to-right from beginning of filename stem. For filenames such as `1917.2019`, `2001.A.Space.Odyssey.1968`, `Blade.Runner.2049.2017`, `Wonder.Woman.1984.2020`, the first 4-digit number is falsely extracted as the release year, wiping out or corrupting the movie title.
- **Affected Benchmark Cases**: `MOVIE-02`, `MOVIE-03`, `MOVIE-04`, `MOVIE-05`, `MOVIE-06`.
- **Target Resolution**: Milestone M2 implements right-to-left year detection (`RE_SCENE_YEAR`) and parenthesis year matching (`RE_PAREN_YEAR`).

#### Gap Group 2: Movie Editions & Multi-Part Split Files (M2: Feature F4)
- **Observed Defect**: `TokenizedFilename` lacks `edition` and `part` fields. Tokens such as `Extended`, `Director's Cut`, `Remastered`, `Criterion`, `Final Cut` are ignored or pollute the movie title. Multi-part files (`CD1`, `CD2`) produce identical destination paths, causing overwrite collisions.
- **Affected Benchmark Cases**: `MOVIE-03`, `MOVIE-07`, `MOVIE-08`, `MOVIE-10`, `MOVIE-11`, `MOVIE-12`, `MOVIE-13`, `MOVIE-14`, `MESSY-01`.
- **Target Resolution**: Milestone M2 adds `RE_EDITION` and `RE_MOVIE_PART`, populating `edition`, `part`, `part_label` in `TokenizedFilename`.

#### Gap Group 3: TV Roman Numerals, Multi-Episodes & Season Packs (M2: Feature F5)
- **Observed Defect**: `RE_SEASON_EPISODE` does not parse Roman numerals (`Season II Episode IV`), multi-episode ranges (`S04E01-E02`, `2x01-02`, `S03E01E02`), or season packs (`Succession.S02.Complete`). These fall back to movie classification or quarantine.
- **Affected Benchmark Cases**: `TV-02`, `TV-03`, `TV-05`, `TV-06`, `TV-08`, `TV-11`.
- **Target Resolution**: Milestone M2 upgrades `RE_SEASON_EPISODE` to support Roman numerals, multi-episode ranges, and season packs.

#### Gap Group 4: Daily / Dated Broadcast TV Shows (M2: Feature F6)
- **Observed Defect**: Shows with broadcast air dates (`2024-01-15`, `2024.03.12`, `2024_02_20`) contain year stamps but no episode numbers. `classifier.py` awards movie points for the year and misclassifies daily TV shows as movies, causing daily broadcasts to overwrite each other.
- **Affected Benchmark Cases**: `DAILY-01`, `DAILY-02`, `DAILY-03`, `DAILY-04`, `DAILY-06`, `DAILY-07`, `DAILY-08`.
- **Target Resolution**: Milestone M2 adds `RE_DAILY_DATE` to populate `is_daily` and `air_date`, steering `classifier.py` to classify dated broadcasts as `tv`.

#### Gap Group 5: Anime Absolute Numbering & Parenthesized Titles (M2: Feature F7)
- **Observed Defect**: `RE_ANIME_RELEASE` rejects parenthesized titles (`Fairy Tail (2014)`) and fails to handle 4-digit episode numbers (`One Piece - 1088`) or OVA releases.
- **Affected Benchmark Cases**: `ANIME-03`, `ANIME-04`, `ANIME-05`, `ANIME-06`, `ANIME-07`, `ANIME-08`, `ANIME-10`, `ANIME-11`.
- **Target Resolution**: Milestone M2 upgrades `RE_ANIME_RELEASE` to support parenthesized titles, cour numbers, and absolute numbering.

#### Gap Group 6: Season 00 Specials Falsy Bug & Template Formatting (M3: Feature F9)
- **Observed Defect**: In `namer.py:164`, `(tokens.season or 1)` evaluates `0` as falsy, converting Season 0 specials into Season 1 and overwriting pilots (`S01E01`). In `config.py:121`, the TV template uses underscore `show_name_{season_episode}` instead of the standard hyphen separator `show_name - {season_episode}`.
- **Affected Benchmark Cases**: `TV-01`, `TV-04`, `TV-07`, `TV-09`, `TV-10`, `SPECIAL-01`, `SPECIAL-02`, `SPECIAL-03`, `SPECIAL-08`, `SPECIAL-09`.
- **Target Resolution**: Milestone M3 fixes `tokens.season is not None` in `namer.py` and standardizes TV destination templates.

#### Gap Group 7: Anime Destination Routing & Library Indexing (M3: Feature F11)
- **Observed Defect**: Anime destination formatting routes files to `Season 01/One Piece_S01E1085 [UnknownGroup].mkv` rather than absolute episode format. In `sorter.py:274`, `dst_p.relative_to(shows_dir)` raises `ValueError` on anime paths, silently dropping anime items from library sync.
- **Affected Benchmark Cases**: `ANIME-01`, `ANIME-02`, `ANIME-04`, `ANIME-09`.
- **Target Resolution**: Milestone M3 adds absolute episode template rendering, stops injecting `[UnknownGroup]`, and fixes relative anime path indexing.

---

## 5. Filesystem Safety & Test Independence Verification

1. **Pure In-Memory Guarantee**:
   All benchmark executions in `test_benchmark.py` and `runner.py` operate on pure in-memory `ScannedFile`, `MediaMetadata`, and `TokenizedFilename` objects. Zero files are opened for write/append, and zero temporary directories are created on disk.
2. **Path Trapping Compliance**:
   All paths passed to `MediaNamer` use isolated mock base directories (`/test_dest`). Host media libraries (`/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`) are never accessed or mutated.
3. **Deterministic Output**:
   Every case execution produces deterministic tokenization and classification results across repeated invocations.
4. **Target for Milestone M4**:
   Following completion of Milestones M2 and M3, running `.venv/bin/pytest tests/benchmark/test_benchmark.py` and `.venv/bin/python -m tests.benchmark.runner` will achieve a **100% pass rate** (64/64 passed) with zero regressions across the 82 baseline unit and integration tests.
