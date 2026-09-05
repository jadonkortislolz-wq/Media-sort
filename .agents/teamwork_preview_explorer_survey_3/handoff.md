# Handoff Report: Sorting Pipeline, Companion Files & Filesystem Safety

**Agent**: Explorer 3 (Survey: Sorting Pipeline, Companion Files & Filesystem Safety)  
**Date**: 2026-09-05  
**Working Directory**: `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_3`  
**Handoff Type**: Hard (Task Complete)

---

## 1. Observation

### 1.1 Filesystem Safety Hazards & Real Media Paths
- **Observation 1.1a (Production Directories Exist on Disk):**
  Command: `ls -ld /md0/jdownloads /md0/movies1 /md0/tv1`
  Output:
  ```
  drwxr-xr-x 138 jkort jkort 36864 Sep  5 18:42 /md0/jdownloads
  drwxr-xr-x 174 root  root  24576 Sep  5 18:08 /md0/movies1
  drwxr-xr-x  50 root  root  12288 Sep  5 18:43 /md0/tv1
  ```
  Real user media exists in these paths with 138, 174, and 50 items respectively.
- **Observation 1.1b (Root `.env` Points to Production Paths with Live Execution):**
  File `/md0/media-sorter/.env`:
  ```ini
  DOWNLOADS_DIR=/md0/jdownloads
  MOVIES_DIR=/md0/movies1
  SHOWS_DIR=/md0/tv1
  DRY_RUN=false
  ACTION=move
  ```
  `cli.py:48-50` loads `.env` by default if present in the working directory.
- **Observation 1.1c (No Root Test Guardrails):**
  Inspecting `/md0/media-sorter/tests`:
  `tests/` contains only `integration/` and `unit/` subdirectories. No `tests/conftest.py` exists. There are no global safety traps or autouse fixtures to intercept writes to `/md0/jdownloads`, `/md0/movies1`, or `/md0/tv1`.

### 1.2 Test Environment Pollution & Reproducible Test Failure
- **Observation 1.2a (Global `os.environ` Mutation in Server):**
  File `/md0/media-sorter/src/media_sorter/server.py:1385-1416`:
  ```python
  if req.confidence_threshold is not None:
      settings.general.confidence_threshold = req.confidence_threshold
      os.environ["CONFIDENCE_THRESHOLD"] = str(req.confidence_threshold)
  ```
- **Observation 1.2b (Reproduced Cross-Test Failure):**
  Command: `.venv/bin/pytest tests/unit/test_server_and_env.py tests/unit/test_config_and_db.py`
  Output:
  ```
  tests/unit/test_server_and_env.py ..............                         [ 82%]
  tests/unit/test_config_and_db.py F..                                     [100%]
  =================================== FAILURES ===================================
  ____________________________ test_settings_defaults ____________________________
      def test_settings_defaults():
          settings = Settings()
          assert settings.general.dry_run is True
  >       assert settings.general.confidence_threshold == 0.75
  E       AssertionError: assert 0.8 == 0.75
  ```

### 1.3 Tokenizer Edge Case Deficiencies
- **Observation 1.3a (Roman Numerals Ignored):**
  In `tokenizer.py:16-29`, `RE_SEASON_EPISODE` requires `\d{1,2}` for seasons and `\d{1,3}` for episodes. Roman numerals are not handled.
  Empirical run:
  `FilenameTokenizer().tokenize(Path("Rome.Season.II.Episode.IV.mkv"))` yields:
  `title: "Rome Season II Episode IV"`, `season: None`, `episode: None`, `is_episodic: False`.
- **Observation 1.3b (Ambiguous Years Corrupt Movie Titles):**
  In `tokenizer.py:42, 235`, `RE_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")`.
  Empirical run:
  - `1917.2019.1080p.mkv` yields `title: ""`, `year: 1917`.
  - `2001.A.Space.Odyssey.1968.mkv` yields `title: ""`, `year: 2001`.
  - `Blade.Runner.2049.2017.mkv` yields `title: "Blade Runner"`, `year: 2049`.
- **Observation 1.3c (Anime Titles with Parentheses Misclassified as Movies):**
  In `tokenizer.py:35`, `RE_ANIME_RELEASE` matches `(?P<title>[^\[\]\(\)]+?)\s*-\s*`. Titles containing parentheses fail this regex.
  Empirical run:
  `[HorribleSubs] Fairy Tail (2014) - 176 [720p].mkv` yields:
  `title: "Fairy Tail"`, `year: 2014`, `is_anime: False`, `is_episodic: False`. `classifier.py` then classifies this anime episode as a Movie!
- **Observation 1.3d (Multi-Part Episode Limitations):**
  Empirical run:
  - `[SubsPlease] Show - 01-02 [1080p].mkv` yields `title: "Show - 01"`, `episode: 2`, `multi_episodes: []`.
  - `Show.1x01-02.mkv` yields `multi_episodes: []`.
  - `Show.S01E01E02E03.mkv` yields `multi_episodes: [1, 2]` (omitting episode 3).

### 1.4 Companion File Pairing, Exclusions & Cleanup Routines
- **Observation 1.4a (Sidecar Extensions & Pairing):**
  `scanner.py:23-28` defines `SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx"}` and `METADATA_EXTS = {".nfo", ".xml", ".json"}`.
  `scanner.py:226-235` pairs sidecars where `s_stem == c_stem or s_stem.startswith(c_stem)`.
  `namer.py:136-145` preserves language suffixes (e.g. `.en.srt`, `.forced.srt`) on output.
- **Observation 1.4b (`.txt` & `.srt` Exclusions):**
  `config.py:114` and `scanner.py:84` include `*.txt` in `exclude_patterns`.
  `server.py:129` excludes `.txt` and `.srt` from `list_files_in_dir()`.
- **Observation 1.4c (Cleanup Routines):**
  `executor.py:610-689` (`clean_empty_directories`) deletes `src.with_suffix(".txt")`, deletes `.txt` files in parent directories and source roots, and `rmdir`s empty directories up to source roots.
  `server.py:845-896` (`delete_download_file`) unlinks target file, deletes companion `.txt`, and removes empty parent folders.

### 1.5 Input Validation & Security Gaps in Server
- **Observation 1.5a (Unsanitized Paths in Manual Sort):**
  `server.py:1130-1155`: `req.title.strip()` is interpolated directly into `final_dst = dest_dir / f"{folder_name}{target.suffix}"` without calling `sanitize_filename_component()`.
- **Observation 1.5b (Arbitrary Image Read in `/api/poster/local`):**
  `server.py:1455-1463`: `p = Path(path).resolve()` is served via `FileResponse(p)` without verifying containment in allowed storage directories.

---

## 2. Logic Chain

1. **Safety Threat from Host Setup (1.1a + 1.1b + 1.1c):**
   - Real media files exist in `/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`.
   - The workspace root `.env` explicitly configures those paths with `DRY_RUN=false` and `ACTION=move`.
   - `cli.py` loads `.env` by default.
   - Without an autouse test trap in `conftest.py`, any test or execution invoking default settings risks scanning and moving production media, violating R5.
2. **Environment Variable Leakage (1.2a + 1.2b):**
   - `POST /api/settings` writes to `os.environ` directly.
   - When `test_server_and_env.py` runs, it leaves `os.environ["CONFIDENCE_THRESHOLD"] = "0.80"`.
   - Any subsequent test instantiating `Settings()` without setting environment variables inherits `0.80` instead of `0.75`.
   - This directly caused the test failure in `test_settings_defaults` when run in sequence.
3. **Parsing Deficiencies Drive Classification Errors (1.3a + 1.3b + 1.3c + 1.3d):**
   - Because `RE_ANIME_RELEASE` rejects parentheses, `Fairy Tail (2014) - 176` falls through to `RE_YEAR`, which extracts `2014` and classifies it as a movie.
   - Because `RE_YEAR` uses first-match `search()`, movies named after years (`1917`, `2001`, `2049`) lose their titles.
   - Because `RE_SEASON_EPISODE` only accepts digits, Roman numeral shows (`Rome Season II Episode IV`) are treated as unclassifiable or non-episodic.
4. **Input Sanitization Omission (1.5a):**
   - While `MediaNamer.generate_destination_path()` rigorously sanitizes components via `sanitize_filename_component()`, `server.py:manual_sort_file()` bypassed `MediaNamer` and manually constructed destination paths without sanitization, exposing the system to invalid character errors or path traversal.

---

## 3. Caveats

- **External Metadata Provider (TMDB/TVmaze):** Investigation was performed with `enable_online_metadata: false` (the default). Network queries to TVmaze for posters and TMDB for classification were not evaluated for live throughput or external rate limits, as tests rely on `MockMetadataProvider` and local poster caches.
- **Coverage Tooling:** `pytest-cov` is not pre-installed in `.venv`. Coverage analysis was performed by direct source code path audit.
- **Non-Linux Platforms:** File locking was verified for Linux (`fcntl.flock`). Windows `msvcrt` execution paths were statically reviewed but not executed on this Linux host.

---

## 4. Conclusion

The sorting pipeline has robust core architecture (two-pass sidecar destination alignment, atomic move/copy fallbacks, and transactional database journaling). However, four critical areas require immediate implementation:
1. **Fulfill R5 (Production Safety):** Add a root `tests/conftest.py` with an `autouse=True` fixture that sanitizes `os.environ` and installs a filesystem trap raising `RuntimeError` if any test attempts to mutate or delete files under `/md0/jdownloads`, `/md0/movies1`, or `/md0/tv1`.
2. **Fix Environment Contamination:** Ensure `/api/settings` tests use `monkeypatch` or that `Settings` is decoupled from process-wide `os.environ`, preventing cross-suite test failures.
3. **Fulfill R4 (Tokenizer Expansion):**
   - Add Roman numeral parsing (`I..XX`) to season and episode detection.
   - Refactor `RE_YEAR` to anchor on release tags or search backwards, preserving titles like `1917`, `2001`, and `2049`.
   - Allow parentheses in anime titles in `RE_ANIME_RELEASE`.
   - Expand multi-part episode parsing for `1x01-02`, triple episodes (`S01E01E02E03`), and anime releases.
4. **Fulfill R3 (Input Validation Hardening):**
   - Apply `sanitize_filename_component()` in `/api/files/manual-sort`.
   - Apply `p.is_relative_to()` boundary checks in `/api/poster/local`.

---

## 5. Verification Method

### 5.1 Verify Current Test Baseline
Run the existing test suite:
```bash
.venv/bin/pytest tests/
```
*Expected:* 75 passed.

### 5.2 Reproduce Environment Contamination Failure
Run the tests in sequence where `test_server_and_env.py` precedes `test_config_and_db.py`:
```bash
.venv/bin/pytest tests/unit/test_server_and_env.py tests/unit/test_config_and_db.py
```
*Expected:* `FAILED tests/unit/test_config_and_db.py::test_settings_defaults - AssertionError: assert 0.8 == 0.75`.

### 5.3 Verify Tokenizer Edge Cases
Run the probe script:
```bash
.venv/bin/python -c '
from pathlib import Path
from media_sorter.tokenizer import FilenameTokenizer
tok = FilenameTokenizer()
for name in ["Rome.Season.II.Episode.IV.mkv", "1917.2019.1080p.mkv", "[HorribleSubs] Fairy Tail (2014) - 176 [720p].mkv"]:
    t = tok.tokenize(Path(name))
    print(name, "-> title:", repr(t.title), "s:", t.season, "e:", t.episode, "yr:", t.year, "anime:", t.is_anime)
'
```
*Expected:* Demonstrates the Roman numeral, ambiguous year, and anime parenthesis failures documented above.

### 5.4 Verify Production Path Protection
Check that `/md0/jdownloads`, `/md0/movies1`, and `/md0/tv1` are untouched:
```bash
ls -ld /md0/jdownloads /md0/movies1 /md0/tv1
```
*Expected:* Modification timestamps and contents remain unchanged.

---
*Handoff report delivered to `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_3/handoff.md`.*
