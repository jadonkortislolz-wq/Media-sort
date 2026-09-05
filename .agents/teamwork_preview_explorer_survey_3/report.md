# Comprehensive Survey Report: Sorting Pipeline, Companion Files & Filesystem Safety

**Agent**: Explorer 3 (Survey: Sorting Pipeline, Companion Files & Filesystem Safety)  
**Date**: 2026-09-05  
**Codebase**: `/md0/media-sorter`  
**Reference Requirement**: `ORIGINAL_REQUEST.md` (R1, R3, R4, R5)

---

## Executive Summary

This report delivers a thorough architectural and implementation survey of the Media Sorter sorting pipeline, tokenization and filename parsing algorithms, companion/sidecar file handling, error handling and defensive fallbacks, and filesystem safety guardrails.

### Critical Findings Overview:
1. **Filesystem Safety Hazard (R5):** Real production media directories exist on the host filesystem (`/md0/jdownloads` with 138 entries, `/md0/movies1` with 174 entries, `/md0/tv1` with 50 entries). The repository's root `.env` file explicitly configures these production paths with `DRY_RUN=false` and `ACTION=move`. If CLI commands or tests execute without strict configuration overrides, they will immediately mutate real user media. Furthermore, tests currently lack a root `conftest.py` safety guardrail to intercept writes to production paths.
2. **Global Environment Mutation & Test Interference:** Updating settings via `/api/settings` (`server.py:1387-1416`) directly mutates `os.environ` (`os.environ["CONFIDENCE_THRESHOLD"] = ...`, etc.). This contaminates the Python process environment. Running `pytest tests/unit/test_server_and_env.py tests/unit/test_config_and_db.py` produces a reproducible test failure in `test_settings_defaults` (`AssertionError: assert 0.8 == 0.75`) due to environment leakage across test suites.
3. **Tokenization and Parsing Deficiencies (R4):**
   - **Roman Numerals:** Entirely missing from episodic and seasonal regexes (`RE_SEASON_EPISODE`). Filenames like `Rome.Season.II.Episode.IV.mkv` completely fail detection (`is_episodic=False`).
   - **Ambiguous Years:** Year matching (`RE_YEAR.search(stem)`) greedily takes the first 4-digit number. In titles like `1917.2019.1080p.mkv` or `2001.A.Space.Odyssey.1968.mkv`, the title year is parsed as the release year, leaving an empty movie title `""`. In `Blade.Runner.2049.2017.mkv`, the year becomes `2049`.
   - **Anime Release Tags with Parentheses:** `RE_ANIME_RELEASE` explicitly forbids parentheses in titles `(?P<title>[^\[\]\(\)]+?)`. Files like `[HorribleSubs] Fairy Tail (2014) - 176 [720p].mkv` fail anime parsing and fall back to being misclassified as movies.
   - **Multi-Part Episodes:** Multi-part episode detection works for `S01E01-E02`, but fails on triple episodes (`S01E01E02E03`), standard scene syntax `1x01-02`, and anime multi-part releases `[SubsPlease] Show - 01-02 [1080p].mkv` (which misparses as title `Show - 01` and episode `2`).
4. **Input Validation and Security Gaps (R3):**
   - In `/api/files/manual-sort` (`server.py:1130-1155`), user-supplied `req.title` is concatenated directly into destination directory and filename paths without invoking `sanitize_filename_component()`.
   - In `/api/poster/local` (`server.py:1455-1463`), `path` is resolved and served without checking boundary containment inside allowed storage directories (arbitrary local image read).
   - In `/api/settings` (`server.py:1385-1398`), directory paths are created via `Path(...).mkdir(parents=True, exist_ok=True)` without catching permission/unreachable errors, and model validation is bypassed by direct attribute assignment.

---

## 1. Sorting Pipeline Architecture

The end-to-end sorting pipeline is coordinated across five primary modules: `scanner.py`, `analyzer.py`, `tokenizer.py`, `classifier.py`, `namer.py`, and `executor.py`, orchestrated by `MediaSorterApp` in `sorter.py`.

```
[ Source Directories ]
         │
         ▼
 1. Scanner (scanner.py)
    ├── _walk_safe (os.scandir, inode cycle prevention, symlink skip)
    ├── File lock verification (fcntl.flock non-blocking)
    ├── File age threshold check (min_file_age_seconds)
    ├── Filter matching (include/exclude patterns; *.txt exclusion)
    └── Sidecar pairing (_pair_sidecars in same directory)
         │
         ▼
 2. Analyzer & Tokenizer (analyzer.py, tokenizer.py)
    ├── Header & container inspection (FLAC, MP3, EBML, MP4, RIFF, JPEG, PNG, ZIP/RAR/7z)
    └── Semantic token extraction (title, year, season, episode, artist, codec, resolution)
         │
         ▼
 3. Classifier (classifier.py)
    ├── Multi-signal heuristic scoring (weights for filename, MIME, streams, duration, tags)
    ├── Library catalog feedback (match_known_show boosting)
    └── Threshold evaluation (below confidence_threshold -> quarantine)
         │
         ▼
 4. Namer & Planner (namer.py, sorter.py, executor.py)
    ├── Pass 1: Primary media destination generation (MediaNamer.generate_destination_path)
    ├── Pass 2: Sidecar destination alignment (_format_sidecar_path)
    ├── Cross-platform filename sanitization (sanitize_filename_component)
    └── Collision detection & policy resolution (_resolve_conflict: RENAME_UNIQUE, SKIP, etc.)
         │
         ▼
 5. Executor (executor.py)
    ├── Inter-process lock acquisition (media_sorter.lock)
    ├── Transactional journal entry (BatchRecord, Operation status=IN_PROGRESS)
    ├── Safe execution (_safe_move: atomic os.replace or temp-copy-atomic-replace)
    ├── Attribute preservation (mtime, permissions, POSIX xattrs)
    ├── Audit record & database caching (FileRecord status=organized)
    ├── Post-move cleanup (clean_empty_directories: .txt deletion & rmdir)
    └── Library index synchronization (record_detected_item)
```

### 1.1 Discovery & Scanning (`scanner.py`)
- **Traversal Mechanism:** `_walk_safe()` uses a stack-based traversal with `os.scandir()`. It explicitly checks `entry.is_symlink()` and continues to prevent following symlinks. It records `(stat.st_dev, stat.st_ino)` in `visited_inodes` to prevent filesystem traversal loops.
- **Active Write Protection:** `is_file_locked(path)` tests `fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)` on POSIX (and `msvcrt.locking` on Windows). If locked, the file is skipped.
- **File Age Verification:** Compares `now - stat.st_mtime` against `min_file_age_seconds` (default 300s in `GeneralSettings`, overridden to 0 in test environments).
- **Filter Evaluation:** Evaluates `_matches_filter()`. Matches `exclude_patterns` first (case-insensitive `fnmatch`), then `include_patterns`. Default exclude patterns exclude `*.txt`, hidden files `.*`, and partial download extensions (`*.part`, `*.crdownload`, `*.!qB`).

### 1.2 Multi-Signal Classification & Library Matching (`classifier.py`, `library.py`)
- **Sidecar Handling:** Sidecars bypass general classification and receive `category="subtitle"|"artwork"|"metadata"|"movie"` with 0.95 confidence if paired with a primary media file, or 0.80 if orphaned (`classifier.py:104-128`).
- **Archive Detection:** Handled immediately if container is `zip`, `rar`, `7z`, `tar`, `gz` (`confidence=0.95`).
- **Video Classification:**
  1. *Home Video:* Camera date stamp in filename or `vid_`/`mov_`/`mvi_` prefix, short duration (<900s), and lack of resolution/scene tags (`confidence=0.88`).
  2. *Documentary:* Keywords `documentary`, `docu`, `bbc.`, `national.geographic` in path or stem (`confidence=0.85-0.95`).
  3. *Anime:* Fansub syntax, release group, or `anime` directory hint (`confidence=0.70-0.98`).
  4. *TV Show:* `tokens.is_episodic` or TV folder naming without year, or episodic duration (`confidence=0.40-0.99`). Boosted by external provider (`provider.search_tv`) or show memory (`match_known_show`).
  5. *Movie:* Year in title (`+0.35`), scene technical tags (`+0.15`), movie directory hint (`+0.15`), duration >= 3600s (`+0.15`). Boosted by provider (`provider.search_movie`).
- **Quarantine Threshold:** Any item where `confidence < confidence_threshold` (default 0.75) is flagged with `needs_quarantine=True` and a human-readable `quarantine_reason`.

### 1.3 Two-Pass Destination Planning & Conflict Resolution (`sorter.py`, `executor.py`)
- **Two-Pass Destination Planning (`sorter.py:159-208`):**
  - Pass 1: Iterates through non-sidecar media files. Resolves destination via `MediaNamer.generate_destination_path(cls_res)` and stores destination in `primary_dest_map[scanned.path] = dst`.
  - Pass 2: Iterates through sidecars (`scanned.is_sidecar`). Passes `primary_dst_path = primary_dest_map.get(scanned.primary_media_path)` to `MediaNamer.generate_destination_path()`.
- **Intra-Batch & On-Disk Conflict Detection (`executor.py:136-204`):**
  - Maintains `allocated_destinations: Dict[Path, PlannedOperation]`.
  - If a target destination is already allocated within the current batch or already exists on disk, `_resolve_conflict()` is invoked.
  - Policies supported: `RENAME_UNIQUE` (`{stem} ({counter}){ext}` loop), `SKIP`, `QUARANTINE`, `REPLACE_IF_HIGHER_QUALITY` (moves existing destination to backup directory before overwriting), `ERROR`.

### 1.4 Atomic Execution & Journaling (`executor.py`)
- **Process Mutual Exclusion:** `acquire_process_lock(lock_path)` locks `media_sorter.lock` using `fcntl.flock(LOCK_EX | LOCK_NB)` to ensure only one process or batch runs at a time (`executor.py:35-70`).
- **Journal State Lifecycle:**
  1. `BatchRecord` created with `status="IN_PROGRESS"`.
  2. For each planned operation, `Operation` created with `status="IN_PROGRESS"`, partial SHA-256 hash (`compute_file_hash`, first 1MB), and backup path if replacing.
  3. Physical move executed via `_safe_move()`. If same filesystem (`st_dev` match), executes atomic `os.replace(src, dst)`. If cross-filesystem, writes to `.tmp_media_sorter_{uuid}_{name}` in destination folder, preserves attributes, verifies size equality, atomically replaces temp file into final destination, and unlinks source.
  4. Permissions applied via `_apply_permissions(dst)`.
  5. `Operation.status` updated to `COMMITTED`, `dst_hash` computed, and `FileRecord` inserted/updated in database.
  6. Batch completion recorded: `status="COMPLETED"` (or `"PARTIAL_FAILURE"` if any operations failed).
- **Crash Recovery:** `MediaExecutor.recover_interrupted_batches()` scans for `Operation.status == "IN_PROGRESS"` left from killed processes and marks them `FAILED` with an error message (`executor.py:590-608`).

---

## 2. Media Tokenization and Filename Parsing Analysis

### 2.1 Regex Pattern Inventory (`tokenizer.py`)

| Regex Constant | Target | Pattern Summary | Limitations Identified |
|---|---|---|---|
| `RE_SEASON_EPISODE` (line 16) | Standard TV seasons & episodes | `s\d{1,2}(?:e\|ep\|ed\|op)\d{1,3}`, `\d{1,2}x\d{1,3}`, `season\s*\d{1,2}...episode\s*\d{1,3}`, `(?:episodes?\|ep)\s*\d{1,4}` | No roman numerals (`Season II`, `Part III`). No support for multi-episodes in `1x01-02` or `S01E01E02E03`. |
| `RE_ANIME_RELEASE` (line 31) | Anime fansub filenames | `^\s*(?:\[(?P<group>[^\]]+)\]\s*)?(?P<title>[^\[\]\(\)]+?)\s*-\s*(?P<episode>\d{1,4})(?:v\d+)?...` | `[^\[\]\(\)]+?` fails if title contains parentheses (e.g. `(2014)` or `(TV)`). Fails releases without ` - ` delimiter. |
| `RE_YEAR` (line 42) | 4-digit release year | `\b(19\d{2}\|20\d{2})\b` | First-match search (`search()`) misidentifies title numbers (e.g. `1917`, `2001`, `2049`) as release years. |
| `RE_RESOLUTION` (line 45) | Video resolution | `\b(2160p\|4k\|1080p\|1080i\|720p\|576p\|480p)\b` | Missing `576i`, `480i`, standard definition labels. |
| `RE_DIMENSIONS` (line 46) | Video dimensions | `\b(?:\d{3,4})x(?P<height>2160\|1080\|720\|576\|480)\b` | Prevents `1920x1080` from being parsed as season 1920 episode 1080. |
| `RE_SOURCE` (line 47) | Source media format | `\b(bluray\|blu-ray\|bdrip\|web-dl\|webrip\|web\|hdtv\|dvdrip\|dvd\|remux)\b` | Missing `UHD BluRay`, `HD-DVD`, `TELESYNC`, `CAM`. |
| `RE_VIDEO_CODEC` (line 48) | Video compression format | `\b(x265\|x264\|h\.?265\|h\.?264\|hevc\|avc\|av1\|xvid\|divx)\b` | Missing `VP9`, `MPEG2`, `VC-1`. |
| `RE_AUDIO_CODEC` (line 49) | Audio stream format | `\b(truehd\|atmos\|dts-hd\|dts\|flac\|aac\|ac3\|ddp?5\.1\|mp3)\b` | Missing `EAC3`, `DTS-X`, `Opus`, `PCM`. |
| `RE_RELEASE_GROUP` (line 50) | Trailing scene release group | `-([A-Za-z0-9_]+)(?:\[.*?\])?$` | Misses bracketed groups at the beginning or groups before technical tags. |
| `RE_MUSIC_TRACK` (line 53) | Music track & disc numbering | `^(?:(?P<disc>\d{1,2})[-_.])?(?P<track>\d{1,3})[\.\s_-]+(?P<title>.+)$` | Requires leading track number. |
| `RE_CAMERA_DATE` (line 60) | Photos & home video dates | `(?:img\|vid...)?[-_]?(?P<year>19\d{2}\|20\d{2})[-_]?(?P<month>\d{2})[-_]?(?P<day>\d{2})...` | Effective for ISO and compact camera naming conventions. |
| `RE_PODCAST_DATE` (line 68) | Dated podcast naming | `^(?P<show>.+?)\s*-\s*(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\s*-\s*(?P<title>.+)$` | Requires exact 3-part hyphen-separated format. |

### 2.2 Concrete Failure Cases Verified by Live Probe

The following edge cases were directly executed against `FilenameTokenizer` in Python 3.14 to observe empirical behavior:

| Filename Tested | Observed Tokenizer Output | Root Cause in Code | Expected Correct Output |
|---|---|---|---|
| `Rome.Season.II.Episode.IV.mkv` | `title: "Rome Season II Episode IV"`, `s: None`, `e: None`, `is_episodic: False` | `RE_SEASON_EPISODE` only accepts `\d{1,2}` for season and `\d{1,3}` for episode; no Roman numeral parser exists. | `title: "Rome"`, `season: 2`, `episode: 4`, `is_episodic: True` |
| `1917.2019.1080p.mkv` | `title: ""`, `year: 1917` | `RE_YEAR.search()` matches the first occurrence `1917`; `prefix = stem[:yr_m.start()]` becomes empty string. | `title: "1917"`, `year: 2019` |
| `2001.A.Space.Odyssey.1968.mkv` | `title: ""`, `year: 2001` | First-match `RE_YEAR` matches `2001`; prefix before index 0 is empty. | `title: "2001 A Space Odyssey"`, `year: 1968` |
| `Blade.Runner.2049.2017.mkv` | `title: "Blade Runner"`, `year: 2049` | `RE_YEAR` matches `2049` as the movie year instead of `2017`. | `title: "Blade Runner 2049"`, `year: 2017` |
| `[HorribleSubs] Fairy Tail (2014) - 176 [720p].mkv` | `title: "Fairy Tail"`, `year: 2014`, `is_anime: False`, `is_episodic: False` (classified as Movie!) | `RE_ANIME_RELEASE` line 35 uses `[^\[\]\(\)]+?`, failing match on titles with `()`. Falls back to `RE_YEAR` and misclassifies as movie! | `title: "Fairy Tail (2014)"`, `episode: 176`, `is_anime: True`, `is_episodic: True` |
| `[SubsPlease] Show - 01-02 [1080p].mkv` | `title: "Show - 01"`, `episode: 2`, `multi_episodes: []` | Second hyphen `- 02` is matched by `RE_ANIME_RELEASE` as the episode delimiter, corrupting the title. | `title: "Show"`, `episode: 1`, `multi_episodes: [1, 2]`, `is_anime: True` |
| `Show.1x01-02.mkv` | `title: "Show 1x01"`, `season: 1`, `episode: 2`, `multi_episodes: []` | `RE_SEASON_EPISODE` branch 2 (`\d{1,2}x\d{1,3}`) has no `episode_end` group. Falls through to anime hyphen match. | `title: "Show"`, `season: 1`, `episode: 1`, `multi_episodes: [1, 2]` |
| `Show.S01E01E02E03.mkv` | `title: "Show"`, `season: 1`, `episode: 1`, `multi_episodes: [1, 2]` | Regex only captures one `episode_end` token; episode 3 is truncated and spilled into title suffix. | `title: "Show"`, `season: 1`, `episode: 1`, `multi_episodes: [1, 2, 3]` |

### 2.3 Proposed Tokenizer Enhancements
1. **Roman Numeral Translation:** Integrate a roman numeral conversion table/regex (`(?i)\b(?:season|series|s)\s*([IVXLCDM]+)\b` and `\b(?:episodes?|ep|part|chapter)\s*([IVXLCDM]+)\b`) converting `I..XX` to integers before or during pattern matching.
2. **Reverse/Contextual Year Resolution:** When multiple 4-digit years exist in the stem, select the one immediately preceding technical tokens (`1080p`, `BluRay`, `x264`) or closest to the end of the stem, reserving preceding years as part of the title (e.g. `1917 (2019)`, `2001: A Space Odyssey (1968)`).
3. **Relaxed Anime Title Parsing:** Allow parentheses in anime titles by replacing `[^\[\]\(\)]+?` with `.+?` anchored by `\s*-\s*(?P<episode>\d{1,4})`.
4. **Multi-Part Sequence Capture:** Support multi-episode chaining (`(?:[eEx-](\d{1,3}))+`) for `S01E01E02E03` and `1x01-02` / `1x01x02`.
5. **Modern Release Tag Recognition:** Expand `RE_SOURCE`, `RE_AUDIO_CODEC`, and add `RE_EDITION` (`EXTENDED`, `DIRECTORS CUT`, `REMASTERED`, `PROPER`, `REPACK`, `IMAX`, `HDR10+`, `DV`).

---

## 3. Companion File Handling & Cleanup Routines

### 3.1 Subtitle & Metadata Pairing
- **Sidecar Extensions Recognized:**
  - Subtitles: `.srt`, `.ass`, `.ssa`, `.vtt`, `.sub`, `.idx` (`scanner.py:23`)
  - Artwork: `.jpg`, `.jpeg`, `.png`, `.webp`, `.tbn` for stems `poster`, `cover`, `folder`, `fanart`, `banner`, `clearart`, `disc`, `logo` (`scanner.py:24-25`)
  - Metadata: `.nfo`, `.xml`, `.json` (`scanner.py:26`)
  - Extras: `-trailer`, `-sample`, `-featurette`, `-behindthescenes`, `-deleted`, `-short` (`scanner.py:27`)
- **Pairing Algorithm (`scanner.py:207-236`):**
  - Scans directory and groups video primaries by `parent` folder.
  - Matches sidecars in the same folder where `s_stem == c_stem` or `s_stem.startswith(c_stem)`.
  - Sets `scanned.primary_media_path = matched_primary.path`.
- **Destination Path Generation (`namer.py:123-158`):**
  - Subtitle: Detects language suffix from source stem: `parts = src_stem.split(".")`; if `len(parts[-1]) in (2, 3, 6)` (e.g. `.en`, `.eng`, `.forced`), appends language code to destination filename: `{primary_stem}.{lang}.{ext}`.
  - Metadata: Matches primary destination stem `{primary_stem}.{ext}` alongside primary video.
  - Artwork: Placed in the parent destination folder with sanitized name (e.g. `poster.jpg`).

### 3.2 Exclusion Policies
- **Scanner Filtering:** `*.txt` is explicitly excluded in `FilterSettings.exclude_patterns` (`config.py:114`) and `Scanner.exclude_patterns` (`scanner.py:84`). Text files are never queued as primary media.
- **Folder Explorer Display Exclusion:**
  - `server.py:129`: `if f.lower().endswith((".txt", ".srt")): continue`
  - In `list_files_in_dir()`, both `.txt` and `.srt` files are excluded from the Folder Explorer table in the web UI.
  - In `inspect_downloads_folder()`, files with `.txt` or `.srt` extensions are ignored when categorizing downloads into shows, unsure groups, and single items.

### 3.3 Post-Organization and Deletion Cleanup Routines
- **Executor Cleanup (`executor.py:610-689`):**
  - `clean_empty_directories(moved_src_paths)` runs after live move batches.
  - *Companion `.txt` deletion:* Calls `src.with_suffix(".txt").unlink()`.
  - *Parent directory ascending cleanup:* Ascends from moved file parent up to (but strictly stopping at) configured source roots.
  - *Directory `.txt` purge:* Deletes any `.txt` files remaining in candidate subdirectories and source roots (`executor.py:650-655, 680-685`).
  - *Empty directory removal:* If a folder has no remaining non-junk entries (ignoring `.DS_Store`, `Thumbs.db`, `desktop.ini`, and `.txt`), it deletes OS junk and removes the directory via `rmdir()`.
- **API File Deletion Cleanup (`server.py:845-896`):**
  - Endpoint `DELETE /api/files/download?name=...` validates that the target is inside `downloads_path`, unlinks the file, deletes companion `target.with_suffix(".txt")`, and ascends parent directories up to `downloads_path`, deleting `.txt` files, junk files, and removing empty directories.

---

## 4. Error Handling, Input Validation & Defensive Fallbacks

### 4.1 System & Filesystem Error Handling

| Component | Error / Failure Mode | Current Handling in Code | Assessment |
|---|---|---|---|
| `Scanner._walk_safe` (`scanner.py:201-205`) | Permission denied / broken directory | Catches `(OSError, PermissionError)` per entry and per directory; logs warning/debug and continues traversal. | **Robust:** Does not crash on unreadable subfolders. |
| `Scanner.scan_directory` (`scanner.py:108`) | Nonexistent source root | `if not root.exists(): logger.warning(...); return []` | **Safe:** Graceful empty list return. |
| `Scanner` (`scanner.py:41-64`) | File locked for writing | `is_file_locked(path)` tests `fcntl.flock` or `msvcrt.locking`; catches `(IOError, OSError, PermissionError)` and skips file. | **Robust:** Prevents reading incomplete torrents/downloads. |
| `MediaAnalyzer.analyze` (`analyzer.py:115`) | Corrupted file header / broken container | `except Exception as e: logger.debug(...); return meta` | **Safe:** Graceful fallback to default container/mime metadata. |
| `MediaExecutor._execute_single_op` (`executor.py:309`) | Source file disappeared between scan and move | `if not src.exists(): raise FileNotFoundError(...)` caught in `execute_batch()`; operation marked `FAILED`, batch marked `PARTIAL_FAILURE`. | **Robust:** Does not crash batch on missing files. |
| `MediaExecutor._safe_move` (`executor.py:390-409`) | Cross-device move failure | Copies to `.tmp_media_sorter_{uuid}_{name}`, checks size equality, atomically replaces into destination, unlinks source. `finally` block unlinks temp file if still present. | **Robust:** Prevents partial/corrupt destination files across filesystems. |
| `MediaExecutor.rollback_batch` (`executor.py:548-570`) | Destination deleted externally before rollback | `if dst.exists(): os.replace(dst, src)` | **Gap:** If `dst` was deleted externally, `reverted_count` is not incremented, but `Operation.status` is still set to `ROLLED_BACK`. |

### 4.2 API Endpoint Input Validation Vulnerabilities

```
Vulnerability 1: Unsanitized Path Construction in Manual Sort
File: src/media_sorter/server.py:1130-1155
Function: manual_sort_file(req: ManualSortRequest)
Issue:
  movie_title = req.title.strip()
  dest_dir = movies_base / folder_name
  final_dst = dest_dir / f"{folder_name}{target.suffix}"
  shutil.move(target, final_dst)
Risk:
  sanitize_filename_component() is NOT called. If req.title contains path traversal (../)
  or filesystem-forbidden characters (< > : " / \ | ? *), shutil.move() can fail or write
  outside intended directory boundaries.
Remediation:
  Wrap title, folder_name, and final_dst components in sanitize_filename_component().

Vulnerability 2: Arbitrary Local Image Disclosure
File: src/media_sorter/server.py:1455-1463
Function: serve_local_poster(path: str)
Issue:
  p = Path(path).resolve()
  if not p.exists() or not p.is_file(): raise HTTPException(404)
  if p.suffix.lower() not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]: raise HTTPException(400)
  return FileResponse(p)
Risk:
  Any image file on the host filesystem can be retrieved via /api/poster/local?path=/path/to/image.png
  because p.is_relative_to(allowed_base_dir) is never checked.
Remediation:
  Verify that p is relative to at least one configured storage directory
  (settings.get_source_paths() or destination directories).

Vulnerability 3: Process-Wide Environment Contamination
File: src/media_sorter/server.py:1385-1436
Function: update_settings(req: SettingsUpdateRequest)
Issue:
  os.environ["DOWNLOADS_DIR"] = req.downloads_dir
  os.environ["CONFIDENCE_THRESHOLD"] = str(req.confidence_threshold)
  settings.save_to_env_file(env_path)
Risk:
  Direct mutation of os.environ pollutes the Python process across test suites.
  Calling Settings() in subsequent tests loads these leaked variables.
Remediation:
  Decouple Settings from process os.environ. Use an explicit Settings instance lifecycle
  and monkeypatch in test environments.
```

---

## 5. Filesystem Safety Guardrails & Test Isolation (R5)

### 5.1 Analysis of Production Media Paths
The host filesystem contains live, populated user media directories:
- `/md0/jdownloads`: 138 entries, ownership `jkort:jkort`
- `/md0/movies1`: 174 entries, ownership `root:root`
- `/md0/tv1`: 50 entries, ownership `root:root`

The root configuration file `/md0/media-sorter/.env` contains:
```ini
DOWNLOADS_DIR=/md0/jdownloads
MOVIES_DIR=/md0/movies1
SHOWS_DIR=/md0/tv1
DRY_RUN=false
ACTION=move
```

### 5.2 Leakage Mechanisms and Safety Risks
1. **Default Config Loading (`cli.py:48-50`):**
   ```python
   env_file = Path(".env")
   if env_file.is_file():
       return Settings.load_from_env_file(env_file)
   ```
   If `media-sorter organize` or `media-sorter scan` is run from the workspace root without arguments, it loads `/md0/jdownloads`, `/md0/movies1`, and `/md0/tv1` with `DRY_RUN=false` and `ACTION=move`!
2. **Server Defaults (`server.py:623`):**
   `create_app(..., env_path=".env")` defaults to `.env`. Calling `POST /api/settings` without overriding `env_path` overwrites the root `.env` file.
3. **Absence of Global Test Guardrails:**
   The `tests/` directory contains no `conftest.py`. There is no global fixture preventing tests from reading `.env` or writing to `/md0/jdownloads`, `/md0/movies1`, or `/md0/tv1`. If a developer writes a test invoking `Settings.load_from_env_file()` or `MediaSorterApp(Settings())` without mock directories, it will access production media!

### 5.3 Test Execution Isolation Proof (Empirical Demonstration)
To prove that test isolation is currently fragile due to environment variable pollution:
```bash
# Running test_server_and_env.py followed by test_config_and_db.py:
.venv/bin/pytest tests/unit/test_server_and_env.py tests/unit/test_config_and_db.py
```
**Result:**
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
Because `test_web_settings_update` in `test_server_and_env.py` mutates `os.environ["CONFIDENCE_THRESHOLD"] = "0.80"`, the subsequent test `test_settings_defaults` fails when instantiating `Settings()`.

### 5.4 Proposed Safety Guardrails (Fulfilling R5)

To guarantee 100% compliance with R5, the following guardrails must be established:

1. **Root `tests/conftest.py` with Production Path Trap:**
   Implement an `autouse=True` session fixture that:
   - Sanitizes `os.environ` of all `DOWNLOADS_DIR`, `MOVIES_DIR`, `SHOWS_DIR`, `ANIME_DIR`, `MEDIA_SORTER_*`, `DRY_RUN`, `CONFIDENCE_THRESHOLD`, `ACTION`.
   - Intercepts file mutation calls (`os.replace`, `shutil.move`, `os.unlink`, `os.remove`, `os.rmdir`, `Path.unlink`, `Path.rmdir`). If any target path starts with `/md0/jdownloads`, `/md0/movies1`, or `/md0/tv1`, raise a `RuntimeError("SAFETY VIOLATION: Attempted mutation of production path in test: " + path)`.
2. **Safe Default for Settings Instantiation:**
   `Settings` should not automatically load the production `.env` unless explicitly instructed via an explicit CLI flag or configuration loader. In testing, `Settings` must always point to isolated temporary directories (`tmp_path`).
3. **Restoration of Clean Environment in Tests:**
   Use `monkeypatch` in `test_server_and_env.py` for `/api/settings` tests, ensuring environment mutations do not persist beyond the test function.

---

## 6. Synthesis and Implementation Recommendations

### 6.1 Architectural Decoupling (R1 Compatibility)
As observed, `server.py` is currently monolithic (4916 lines, including ~3400 lines of inline HTML/CSS/JS in `render_dashboard()`).
- Extract the web dashboard HTML/CSS/JS into external template/static files or a dedicated `ui.py` module.
- Decouple route handlers into modular FastAPI routers (`routes/status.py`, `routes/files.py`, `routes/quarantine.py`, `routes/batches.py`, `routes/settings.py`).
- Maintain exact REST API request signatures and response schemas for 100% contract backward compatibility.

### 6.2 Tokenization & Filename Parsing Improvements (R4 Compatibility)
- Add roman numeral normalization (`roman_to_int`) for seasons and episodes.
- Improve year extraction to search backwards or anchor against technical tags to prevent movie titles like `1917`, `2001`, and `2049` from losing their titles.
- Permit parentheses in anime titles in `RE_ANIME_RELEASE`.
- Expand multi-part episode parsing for `S01E01E02E03`, `1x01-02`, and anime releases.

### 6.3 Companion File & Filesystem Safety Verification (R3, R5 Compatibility)
- Add input sanitization (`sanitize_filename_component`) to `/api/files/manual-sort`.
- Add path boundary validation (`p.is_relative_to(...)`) to `/api/poster/local`.
- Create `tests/conftest.py` with filesystem mutation traps targeting `/md0/jdownloads`, `/md0/movies1`, and `/md0/tv1`.

---
*Report prepared by Explorer 3.*
