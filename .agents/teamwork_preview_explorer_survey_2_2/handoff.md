# Handoff Report: Test Suite, Infrastructure, Filesystem Isolation & Benchmark Requirements (Survey 2.2)

**Agent**: Explorer 2 (Survey 2.2: Test Infrastructure, Filesystem Isolation & Benchmark Requirements)  
**Date**: 2026-09-05  
**Codebase**: `/md0/media-sorter`  
**Milestone**: Phase 0 Survey (Follow-up Request)  
**Status**: Complete  

---

## 1. Observation

### 1.1 Test Suite Structure and Configuration
- **Directory Layout**:
  - `tests/`: Contains two subdirectories: `tests/integration/` and `tests/unit/`.
  - No `tests/e2e/` directory exists; the single end-to-end integration test resides in `tests/integration/test_end_to_end.py`.
  - Total test files: 11 files (2 integration, 9 unit).
  - Test files:
    - `tests/integration/test_end_to_end.py` (1 test)
    - `tests/integration/test_messy_filenames_and_fuzz.py` (7 tests: 6 parametrized cases + 1 Hypothesis fuzz test)
    - `tests/unit/test_analyzer.py` (5 tests)
    - `tests/unit/test_classifier.py` (14 tests)
    - `tests/unit/test_config_and_db.py` (3 tests)
    - `tests/unit/test_executor_and_rollback.py` (7 tests)
    - `tests/unit/test_library_and_groups.py` (4 tests)
    - `tests/unit/test_namer.py` (6 tests)
    - `tests/unit/test_quarantine.py` (2 tests)
    - `tests/unit/test_server_and_env.py` (14 tests)
    - `tests/unit/test_tokenizer.py` (12 tests)
- **Configuration Files**:
  - `pytest.ini`: **Does not exist** anywhere in the project.
  - `conftest.py`: **Does not exist** in root or anywhere in `tests/`.
  - `pyproject.toml`: Contains `[tool.poetry.group.dev.dependencies]` with `pytest = ">=8.0.0"`, `pytest-asyncio = ">=0.23.0"`, `hypothesis = ">=6.100.0"`, `black = ">=24.0.0"`, `isort = ">=5.13.0"`. It **lacks** a `[tool.pytest.ini_options]` section.
  - Neither `coverage` nor `pytest-cov` is listed in `pyproject.toml` or installed in `.venv`.

### 1.2 Test Execution Metrics and Output
- **Execution Command**: `.venv/bin/pytest -v` (Note: `poetry` is not in `PATH`; executing `.venv/bin/pytest` directly is required).
- **Collected Items**: Exactly 75 items (`75 passed in 1.42s`).
- **Pass Rate**: 100% (75/75 passed).
- **Warnings Observed**: 2 deprecation warnings:
  ```text
  .venv/lib/python3.14/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
  .venv/lib/python3.14/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
  ```
- **Execution Durations**:
  All 75 tests run in ~1.4 seconds. Slowest test is `test_sanitize_filename_component_fuzz` (Hypothesis, 150 examples, 0.08s), followed by web server tests (0.03s - 0.06s).

### 1.3 Filesystem Safety and Isolation State
- **Production Media Directories**:
  The host filesystem contains real, populated media libraries:
  - `/md0/jdownloads` (137 directory items, owned by `jkort:jkort`)
  - `/md0/movies1` (174 directory items, owned by `root:root`)
  - `/md0/tv1` (53 directory items, owned by `root:root`)
- **Default Environment Hazard**:
  The workspace root `.env` (`/md0/media-sorter/.env`) explicitly configures:
  ```ini
  DOWNLOADS_DIR=/md0/jdownloads
  MOVIES_DIR=/md0/movies1
  SHOWS_DIR=/md0/tv1
  DRY_RUN=false
  ACTION=move
  ```
- **Settings Auto-Loading**:
  `src/media_sorter/config.py:198-204` defines `SettingsConfigDict(env_file=".env", ...)` and `model_post_init` lines 223-250 read `os.getenv("DOWNLOADS_DIR")`, `MOVIES_DIR`, `SHOWS_DIR`, `DRY_RUN`, `ACTION`. If `Settings()` is instantiated without arguments, it binds directly to production folders with `dry_run=False` and `action=move`!
- **Current Isolation Mechanism**:
  Tests achieve isolation solely through cooperative manual configuration inside local fixtures:
  - `tests/integration/test_end_to_end.py:11-28`: `library_environment` fixture explicitly points `settings.storage.source_dirs` and `settings.storage.destination_base` to `tmp_path`.
  - `tests/unit/test_executor_and_rollback.py:9-24`: `temp_env` fixture explicitly overrides paths to `tmp_path`.
  - `tests/unit/test_server_and_env.py:9-33`: `web_env` fixture explicitly overrides paths to `tmp_path`.
- **Zero Safety Traps in Codebase**:
  There are **no** `autouse` fixtures, no mock filesystem traps, and no permission/path interception mechanisms in `tests/`. If any new test or untested codepath executes `MediaSorterApp(Settings())` without explicitly overriding every storage path, it will directly read, move, or unlink real media in `/md0/jdownloads`, `/md0/movies1`, or `/md0/tv1`.
- **Environment Leakage Across Tests**:
  `tests/unit/test_server_and_env.py:109` executes `client.post("/api/settings", json={"confidence_threshold": 0.80})`. In `src/media_sorter/server.py:1406`, this mutates `os.environ["CONFIDENCE_THRESHOLD"] = "0.8"`.
  When executing tests where `test_server_and_env.py` precedes `test_config_and_db.py`:
  ```bash
  .venv/bin/pytest tests/unit/test_server_and_env.py tests/unit/test_config_and_db.py
  ```
  Result:
  ```text
  FAILED tests/unit/test_config_and_db.py::test_settings_defaults - AssertionError: assert 0.8 == 0.75
  ```
  This proves cross-test environment contamination occurs without global test environment sanitization.

### 1.4 Baseline Benchmark Gap Probe
A live empirical probe of 13 representative filenames across all 6 media domains revealed a baseline pass rate of only **61.5%** (8 passed, 5 failed):
- `TV-04 (Roman numerals)`: `Rome.Season.II.Episode.IV.mkv` -> Classified as `movie` (`title: 'Rome Season II Episode IV', season: None, episode: None`). **FAIL**.
- `ANIME-03 (Anime with title paren)`: `[HorribleSubs] Fairy Tail (2014) - 176 [720p].mkv` -> Classified as `anime` with `title: 'Fairy Tail'`, but `season: None, episode: None, year: 2014`. **FAIL**.
- `MOVIE-02 (Ambiguous Year)`: `1917.2019.1080p.BluRay.x264.mkv` -> Classified as `movie` with `title: ''`, `year: 1917`. **FAIL**.
- `MOVIE-03 (Future Year)`: `Blade.Runner.2049.2017.2160p.mkv` -> Classified as `movie` with `title: 'Blade Runner'`, `year: 2049` instead of `2017`. **FAIL**.
- `DAILY-01 (Daily Show)`: `The.Daily.Show.2024-01-15.1080p.HDTV.mkv` -> Classified as `movie` with `title: 'The Daily Show'`, `year: 2024` instead of TV with date stamp. **FAIL**.

---

## 2. Logic Chain

1. **Premise 1: Acceptance Criteria Mandate 100% Pass Rate & Zero Regressions.**
   - `ORIGINAL_REQUEST.md` lines 30 and 68 specify: "`pytest tests/` runs with a 100% pass rate across all existing 75 unit/integration tests and any newly added tests with zero regressions," and "100% of benchmark test cases pass with zero unhandled exceptions."
   - The current baseline is 75 tests passing in 1.42 seconds. Any new benchmark or safety fixture must preserve these 75 tests without regressions.

2. **Premise 2: Production Filesystem Hazard Requires Active Guardrails (R5).**
   - Host directories `/md0/jdownloads`, `/md0/movies1`, and `/md0/tv1` exist and contain live media.
   - `Settings()` defaults to reading `.env`, which points to these directories with `DRY_RUN=false` and `ACTION=move`.
   - Because existing tests only use local cooperative fixtures (`tmp_path`) and have no root `conftest.py`, a developer error or missing fixture override could cause irreversible data loss on production drives.
   - Therefore, a global `tests/conftest.py` with an `autouse=True` filesystem safety trap must be installed to intercept and block all mutating syscalls targeting protected paths.

3. **Premise 3: Environment Pollution Breaks Test Independence.**
   - `server.py` mutates `os.environ` during `POST /api/settings`.
   - Running tests out of alphabetical order causes `test_config_and_db.py` to fail.
   - Therefore, `tests/conftest.py` must include an `autouse=True` environment sanitization fixture that isolates and restores `os.environ` per test.

4. **Premise 4: R2 Benchmark Verification Suite Requires Offline, Pure In-Memory Architecture.**
   - The verification suite must validate parsing, classification, and destination resolution across TV, Anime, Movies, Specials, Daily Shows, and Messy filenames.
   - `FilenameTokenizer.tokenize()`, `MediaClassifier.classify()`, and `MediaNamer.generate_destination_path()` all operate on pure Python data structures (`Path`, `ScannedFile`, `TokenizedFilename`, `MediaMetadata`, `ClassificationResult`).
   - By structuring the benchmark suite around in-memory instances and mock metadata, 100+ real-world filenames can be verified in milliseconds with 0 network calls, 0 disk writes, and 0 mutation risk.

---

## 3. Caveats

1. **Poetry Binary Absence in PATH**:
   `poetry` is not installed or available in the shell PATH. Running `poetry run pytest` fails with exit code 127. All automated commands and documentation must specify `.venv/bin/pytest` or invoke python via `.venv/bin/python -m pytest`.
2. **Coverage Package Status**:
   `pytest-cov` and `coverage` are currently not installed in the `.venv` environment. To fulfill R4's 90% coverage verification requirement, `pytest-cov` and `coverage` will need to be installed in the virtual environment or added to `pyproject.toml`.
3. **Hypothesis Cache Directory**:
   Hypothesis writes cache files to `.hypothesis/` in the project root. This is standard behavior and does not touch user media paths.

---

## 4. Conclusion & Concrete Architectural Design

### 4.1 Root `tests/conftest.py` Specification (Fulfilling R5)
A root `tests/conftest.py` must be established containing:
1. **`protect_production_filesystem` (`autouse=True`, session scope)**:
   - Monkeypatches `os.remove`, `os.unlink`, `os.replace`, `os.rename`, `os.mkdir`, `os.rmdir`, `os.makedirs`, `shutil.move`, `shutil.copy`, `shutil.copy2`, `shutil.copytree`, `shutil.rmtree`, `Path.unlink`, `Path.rmdir`, `Path.mkdir`, `Path.rename`, `Path.replace`, `Path.write_text`, `Path.write_bytes`, and built-in `open` (for write/append/create modes).
   - Verifies whether any target path resolves to or is inside `/md0/jdownloads`, `/md0/movies1`, or `/md0/tv1`.
   - If matched, raises `RuntimeError("FILESYSTEM SAFETY TRAP: Forbidden write/delete operation targeting production path '{target}' in test execution!")`.
2. **`isolate_test_environment` (`autouse=True`, function scope)**:
   - Captures `os.environ` before each test and restores it in teardown.
   - Strips all `DOWNLOADS_DIR`, `MOVIES_DIR`, `SHOWS_DIR`, `ANIME_DIR`, `SOURCE_DIR`, `TV_DIR`, `DRY_RUN`, `ACTION`, `CONFIDENCE_THRESHOLD`, and `MEDIA_SORTER_*` variables so `Settings()` defaults remain clean.
3. **`block_external_network` (`autouse=True`, session scope)**:
   - Intercepts `socket.socket.connect` to prevent any unexpected outbound HTTP/API calls during test execution, ensuring strict offline compliance.

### 4.2 Benchmark Dataset Architecture (Fulfilling R2)
Location: `tests/benchmark/benchmark_cases.py` (or `tests/data/benchmark_dataset.py`)
Data structure:
```python
@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    domain: str                            # TV, Anime, Movie, Specials, Daily, Messy
    filename: str                          # Raw media filename
    expected_category: str                 # tv, anime, movie, podcast, etc.
    expected_title: str                    # Normalized title
    expected_year: Optional[int] = None    # Expected release year
    expected_season: Optional[int] = None  # Expected season
    expected_episode: Optional[int] = None # Expected episode
    expected_multi_episodes: Optional[List[int]] = None
    expected_date: Optional[str] = None    # YYYY-MM-DD
    expected_edition: Optional[str] = None # Director's Cut, Extended, etc.
    expected_part: Optional[str] = None    # CD1, Part 1, etc.
    expected_group: Optional[str] = None   # Release group
    expected_destination_subpath: Optional[str] = None
    edge_case_type: str                    # Taxonomy tag
```

#### Dataset Coverage Inventory:
| Domain | Representative Filename Patterns | Target Edge Case Addressed |
|---|---|---|
| **Standard TV** | `Breaking.Bad.S05E14.Ozymandias.1080p.BluRay.x264-ROVERS.mkv`<br>`Stranger.Things.S04E01-E02.Chapter.One.720p.WEB-DL.mkv`<br>`House.M.D.S03E01E02.1080p.mkv`<br>`The.Wire.1x09.HDTV.mkv`<br>`The.Office.2x01-02.mkv`<br>`Rome.Season.II.Episode.IV.mkv`<br>`Doctor Who Season 5 Episode 1 Eleventh Hour.mkv`<br>`Succession.S02.Complete.1080p.WEB-DL.mkv` | SxxExx, multi-ep ranges (`E01-E02`), concatenated multi-ep (`E01E02`), scene `1x09`, scene multi-ep `2x01-02`, Roman numerals (`Season II Episode IV`), season packs. |
| **Anime** | `[SubsPlease] Frieren - Beyond Journey's End - 01 (1080p) [ABCD1234].mkv`<br>`[SubsPlease] 葬送のフリーレン - 12 (1080p) [98E7B1A2].mkv`<br>`[HorribleSubs] Fairy Tail (2014) - 176 [720p].mkv`<br>`[Erai-raws] One Piece - 1088 [1080p].mkv`<br>`BLEACH꞉ Sennen Kessen-hen - 27 [E89717B7].mkv`<br>`[SubsPlease] Dungeon Meshi - 01-02 (1080p).mkv`<br>`[Judas] Fate Stay Night - Heaven's Feel - I. Presage Flower [BD 1080p].mkv`<br>`[TaigaSubs] Attack on Titan OVA - 01 [720p].mkv`<br>`Naruto Episode 207 The Supposed Sealed Ability.mkv` | Standard fansubs, Unicode/Kanji titles, parentheses in titles, 4-digit absolute numbering, no-group releases, anime multi-episodes, anime OVAs, standalone episode keywords. |
| **Movies** | `Inception.2010.1080p.BluRay.x264-FraMeSToR.mkv`<br>`1917.2019.1080p.BluRay.x264.mkv`<br>`2001.A.Space.Odyssey.1968.REMASTERED.1080p.mkv`<br>`Blade.Runner.2049.2017.2160p.mkv`<br>`Class.of.1999.1990.720p.mkv`<br>`The.Lord.of.the.Rings.The.Fellowship.of.the.Ring.2001.Extended.CD1.avi`<br>`Kill.Bill.Vol.1.2003.1080p.mkv`<br>`Mission.Impossible.Dead.Reckoning.Part.One.2023.2160p.mkv`<br>`Avatar.2009.Extended.Collector's.Edition.1080p.mkv`<br>`Apocalypse.Now.1979.Final.Cut.2160p.mkv` | Standard year extraction, year in title (`1917`, `2001`, `1999`), future year in title (`2049`), multi-part movies (`CD1`, `CD2`, `Part One`), special editions (`Extended`, `Final Cut`, `Collector's Edition`). |
| **Specials & Extras** | `The.Office.S00E01.The.Outtakes.mkv`<br>`Doctor.Who.S00E25.The.Day.of.the.Doctor.1080p.mkv`<br>`Inception.2010-behindthescenes.mkv`<br>`Interstellar.2014-trailer.mp4`<br>`Breaking.Bad.S05E00.Special.mkv` | Season 00 TV specials, sidecar trailers, bonus featurettes, deleted scenes. |
| **Daily / Dated Shows** | `The.Daily.Show.2024-01-15.1080p.HDTV.mkv`<br>`The.Tonight.Show.Starring.Jimmy.Fallon.2024.03.12.720p.mkv`<br>`Last.Week.Tonight.with.John.Oliver.2023-11-05.1080p.mkv`<br>`Late.Night.with.Seth.Meyers.2024_02_20.720p.mkv`<br>`The Daily - 2026-03-12 - The Sunday Read.mp3` | ISO dated TV shows (`YYYY-MM-DD`), dot-separated dates (`YYYY.MM.DD`), underscore dates, dated podcasts. |
| **Messy & Complex** | `Amélie.2001.PROPER.REMASTERED.1080p.BluRay.x264-CiNEFiLE.mkv`<br>`Wolfs.2024.1080p.Apple.TV.WEB-DL.DDP5.1.Atmos.H.264.mkv`<br>`Gladiator.II.2024.1080p.HDTV.x264-[rartv].mkv`<br>`Interstellar.1920x1080.mkv`<br>`[YTS.MX] Movie Title - 2024 [1080p].mkv`<br>`The.Dark.Knight.2008.1080p.forced.srt`<br>`Show: "Special" <Episode> | 1?.mkv`<br>`CON.mp4` | Accented characters, Apple TV/HDTV scene tags, bracket release group with year (non-anime), resolution dimensions (`1920x1080`), subtitle language tags (`.forced.srt`), illegal filesystem characters, Windows reserved device names. |

### 4.3 Benchmark Runner and Reporting Mechanism
1. **Pytest Benchmark Runner (`tests/benchmark/test_benchmark.py`)**:
   - Parametrized over all cases: `@pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c.id)`
   - Pure in-memory execution: invokes `tokenizer.tokenize()`, `classifier.classify()`, `namer.generate_destination_path()`.
   - Executes with `provider=None` and `MediaMetadata(duration_seconds=...)`. Zero network, zero disk writes.
2. **Diagnostic Report Generator (`tests/benchmark/reporter.py`)**:
   - Implements a custom pytest hook or standalone runner (`python -m tests.benchmark.runner`):
     - Calculates per-category pass rate, failure details, and execution time.
     - Renders a colorized Rich terminal table summarizing:
       `Domain | Total | Passed | Failed | Pass Rate %`
     - Outputs machine-readable `benchmark_summary.json` containing exact diffs for any failed case.

---

## 5. Verification Method

### 5.1 Existing Test Suite Verification
Run the existing test suite using the virtualenv pytest binary:
```bash
.venv/bin/pytest -v
```
**Expected Result**:
- Exactly 75 passed tests in < 2 seconds.
- Zero failures, zero errors.

### 5.2 Environment Contamination Verification
Reproduce the cross-test environment contamination failure:
```bash
.venv/bin/pytest tests/unit/test_server_and_env.py tests/unit/test_config_and_db.py
```
**Expected Result**:
- `test_settings_defaults` fails with `AssertionError: assert 0.8 == 0.75` due to leaked `CONFIDENCE_THRESHOLD`.
- Demonstrates why `tests/conftest.py` with `isolate_test_environment` is necessary.

### 5.3 Safety Guardrail Invalidation Condition
If any test or runner code can perform a write (`Path.write_text`, `shutil.move`, `os.remove`) inside `/md0/jdownloads`, `/md0/movies1`, or `/md0/tv1` without raising a `RuntimeError`, the safety guardrail is invalid.
After implementing `tests/conftest.py`, running:
```python
def test_safety_trap():
    with pytest.raises(RuntimeError, match="FILESYSTEM SAFETY TRAP"):
        Path("/md0/jdownloads/illegal_probe.txt").write_text("violation")
```
must pass, confirming active protection.
