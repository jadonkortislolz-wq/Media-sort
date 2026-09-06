# Deep-Dive Investigation & Architectural Design Report: Companion Files, Input Validation, and Database Safety

**Author**: `teamwork_preview_explorer_m2_3` (Explorer Archetype)  
**Date**: 2026-09-06  
**Target Codebase**: `/md0/media-sorter` (`src/media_sorter/`)  
**Milestone Focus**: M2 / M1 Hardening — Companion File Pairing, Input Sanitization, Storage Boundaries, Rollback Resilience, and Database Concurrency.

---

## 1. Executive Summary

This report delivers a thorough architectural investigation and concrete implementation designs for three core areas of the **Media Sorter** application:
1. **Companion File Handling & Cleanup**: Hardening sidecar discovery and pairing (`.srt`, `.sub`, `.ass`, `.nfo`), ensuring atomic synchronization between primary video files and their companions during moves and conflict resolutions, verifying safe recursive empty directory cleanup without risking source roots, and confirming `.txt`/`.srt` exclusions in Folder Explorer.
2. **Input Sanitization & Security Guardrails in `server.py`**: Eradicating path traversal and illegal filesystem characters (`: * ? " < > | / \`) in manual sort endpoints, handling Windows reserved device names (`CON.mp4 -> _CON.mp4`, `NUL`, `AUX`, `PRN`, `COM1-9`, `LPT1-9`), and enforcing strict storage boundary containment checks in `/api/poster/local` to prevent arbitrary file disclosure.
3. **Database & Transaction Scoping**: Fixing broken `scoped_session` re-instantiations in `db.py` to prevent thread-local connection leaks and ensure SQLite WAL concurrency, correcting rollback batch status handling on partial failures in `executor.py`, handling cross-device links during reverse moves, restoring database consistency (`FileRecord` and `LibraryItem.item_count`), and implementing comprehensive mutual exclusion locking across sort runs, rollbacks, and manual operations.

---

## 2. Problem Boundary & Scope Analysis

| Area | Current Source Files | Associated Tests | Core Vulnerabilities / Deficiencies |
|---|---|---|---|
| **Companion Files & Cleanup** | `src/media_sorter/scanner.py`<br>`src/media_sorter/executor.py`<br>`src/media_sorter/sorter.py`<br>`src/media_sorter/namer.py` | `tests/unit/test_executor_and_rollback.py`<br>`tests/unit/test_server_and_env.py` | • Prefix matching in `_pair_sidecars` lacks delimiter checks and candidate ordering (e.g. `Show - 10.srt` falsely pairs with `Show - 1.mkv`).<br>• Subtitles in `Subs/` subfolders fail to pair.<br>• Sidecars are detached from primary operations during conflict resolution (primary renamed to `(1)`, sidecar orphaned).<br>• Empty directory cleanup does not prune newly created empty destination dirs on rollback. |
| **Input Sanitization & Security** | `src/media_sorter/server.py` | `tests/unit/test_server_and_env.py` | • `/api/files/manual-sort` accepts unescaped `req.title` allowing forbidden characters (`: * ? " < > \|`) and path traversal (`../../`).<br>• Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`) unhandled in manual sort and quarantine resolve.<br>• `/api/poster/local` accepts arbitrary absolute paths, exposing all system image files without boundary checks. |
| **Database & Transaction Scoping** | `src/media_sorter/db.py`<br>`src/media_sorter/executor.py`<br>`src/media_sorter/sorter.py`<br>`src/media_sorter/quarantine.py` | `tests/unit/test_config_and_db.py`<br>`tests/unit/test_executor_and_rollback.py` | • `get_db_session` instantiates a new `scoped_session` on every call and never calls `session_factory.remove()`, causing connection leaks.<br>• `rollback_batch` sets `batch.status = "ROLLED_BACK"` even when operations fail.<br>• `rollback_batch` uses `os.replace` which fails across filesystems with `EXDEV`.<br>• `acquire_process_lock` is omitted in `rollback()`, `rollback_all()`, manual sort, and quarantine undo.<br>• Synchronous `sorter.run()` in `auto_sort_worker` blocks the async event loop. |

---

## 3. Deep-Dive Investigation: Companion File Handling & Cleanup

### 3.1 Sidecar Pairing in `scanner.py` and `namer.py`

#### Observation & Current Code
In `src/media_sorter/scanner.py:23-28`:
```python
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx"}
ARTWORK_NAMES = {"poster", "cover", "folder", "fanart", "banner", "clearart", "disc", "logo"}
ARTWORK_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tbn"}
METADATA_EXTS = {".nfo", ".xml", ".json"}
EXTRA_TAGS = {"-trailer", "-sample", "-featurette", "-behindthescenes", "-deleted", "-short"}
```
And in `_pair_sidecars` (lines 206–236):
```python
def _pair_sidecars(
    self,
    sidecars: List[ScannedFile],
    primaries: List[ScannedFile],
    all_discovered: List[ScannedFile],
) -> None:
    primaries_by_dir: Dict[Path, List[ScannedFile]] = {}
    for p in primaries:
        primaries_by_dir.setdefault(p.path.parent, []).append(p)

    for s in sidecars:
        parent = s.path.parent
        candidates = primaries_by_dir.get(parent, [])

        matched_primary = None
        s_stem = s.path.stem.lower()

        for c in candidates:
            c_stem = c.path.stem.lower()
            if s_stem == c_stem or s_stem.startswith(c_stem):
                matched_primary = c
                break

        if matched_primary:
            s.primary_media_path = matched_primary.path

        all_discovered.append(s)
```

#### Defects & Edge-Case Vulnerabilities
1. **Candidate Order & Prefix Collision**:
   `candidates` is iterated in arbitrary filesystem traversal order.
   - If a folder contains `Movie.mkv` and `Movie.Part2.mkv`:
     For sidecar `Movie.Part2.en.srt`, `s_stem` is `movie.part2.en`.
     If `Movie.mkv` appears first in `candidates`, `s_stem.startswith("movie")` evaluates to `True`! `Movie.Part2.en.srt` is incorrectly paired with `Movie.mkv`.
   - If a folder contains `Show - 1.mkv` and `Show - 10.mkv`:
     For sidecar `Show - 10.srt`, `s_stem` is `show - 10`.
     `s_stem.startswith("show - 1")` evaluates to `True`!
     `Show - 10.srt` is incorrectly paired with `Show - 1.mkv`.
2. **Missing Boundary Delimiter Check**:
   `s_stem.startswith(c_stem)` matches substrings without verifying word boundaries. A sidecar only belongs to a primary if `s_stem == c_stem` OR `s_stem.startswith(c_stem)` followed immediately by a standard delimiter (`.`, `-`, `_`, ` `) followed by a language code (`.en`, `.forced`, `.eng`, `.zh-CN`) or extra tag (`-trailer`, `-sample`).
3. **Subfolder Subtitles (`Subs/`, `Subtitles/`)**:
   In multi-file releases, subtitle tracks are often nested in a `Subs/` or `Subtitles/` subfolder (e.g. `/Downloads/MovieName/Subs/en.srt` or `/Downloads/MovieName/Subtitles/MovieName.srt`).
   Because `parent = s.path.parent` evaluates to `/Downloads/MovieName/Subs`, `primaries_by_dir.get(parent, [])` is empty. The subtitles remain completely unpaired (`s.primary_media_path = None`) and are moved as orphan files into the root subtitle directory.
4. **Directory-Level Sidecars (`poster.jpg`, `movie.nfo`)**:
   Artwork and movie NFOs usually have generic stems (`poster`, `folder`, `movie`, `tvshow`). They do not start with the video file's stem. If there is exactly one primary movie file in the directory, directory-level artwork and NFOs should pair with that movie.

#### Proposed Design for `_pair_sidecars`
```python
def _pair_sidecars(
    self,
    sidecars: List[ScannedFile],
    primaries: List[ScannedFile],
    all_discovered: List[ScannedFile],
) -> None:
    """Robustly associate sidecar files (.srt, .sub, .ass, .nfo, artwork) with primary media."""
    primaries_by_dir: Dict[Path, List[ScannedFile]] = {}
    for p in primaries:
        primaries_by_dir.setdefault(p.path.parent.resolve(), []).append(p)

    for s in sidecars:
        parent = s.path.parent.resolve()
        candidates = primaries_by_dir.get(parent, [])

        # Support subdirectories like Subs/ or Subtitles/
        if not candidates and parent.name.lower() in ("subs", "subtitles", "sub"):
            parent = parent.parent
            candidates = primaries_by_dir.get(parent, [])

        matched_primary = None
        s_stem = s.path.stem.lower()

        # Sort candidates longest stem first so "Movie.Part2" matches before "Movie"
        sorted_candidates = sorted(candidates, key=lambda c: len(c.path.stem), reverse=True)

        for c in sorted_candidates:
            c_stem = c.path.stem.lower()
            if s_stem == c_stem:
                matched_primary = c
                break
            # Check delimiter boundary: must be followed by '.', '-', '_', or ' '
            if s_stem.startswith(c_stem) and len(s_stem) > len(c_stem):
                next_char = s_stem[len(c_stem)]
                if next_char in (".", "-", "_", " "):
                    matched_primary = c
                    break

        # Fallback for single-video directories with generic sidecars (movie.nfo, poster.jpg)
        if not matched_primary and len(candidates) == 1:
            if s.sidecar_type in ("metadata", "artwork") or s.path.suffix.lower() in METADATA_EXTS or s.path.suffix.lower() in SUBTITLE_EXTS:
                matched_primary = candidates[0]

        if matched_primary:
            s.primary_media_path = matched_primary.path

        all_discovered.append(s)
```

---

### 3.2 Atomic Move of Primary and Companion Files

#### Current Defect: Conflict Resolution Decoupling
In `sorter.py:159-209`:
- `build_plan()` creates operations for primary media in Pass 1.
- Pass 2 computes sidecar destinations using `primary_dest_map.get(scanned.primary_media_path)`.
- When `executor.execute_batch()` is called, `executor.plan_operations()` is run:
  ```python
  if target_dst.exists():
      target_dst = self._resolve_conflict(item.src, target_dst)
      item.conflict_resolved_dst = target_dst
  ```
- **The Critical Flaw**:
  If `Movie (2024).mkv` collides on disk, `_resolve_conflict` renames it to `Movie (2024) (1).mkv`.
  However, the companion subtitle `Movie (2024).en.srt` was planned separately! Its `dst` remains `Movie (2024).en.srt`.
  During execution:
  - Video moves to `Movie (2024) (1).mkv`.
  - Subtitle moves to `Movie (2024).en.srt`.
  - The video file loses its subtitle association, and the subtitle overwrites or mismatches existing files.
  - Under `ConflictPolicy.SKIP`, the video is skipped, but the subtitle moves regardless!

#### Proposed Atomic Execution Design
1. **PlannedOperation Association**:
   Add `primary_src: Optional[Path] = None` to `PlannedOperation`.
   When creating sidecar operations in `sorter.py:build_plan`:
   ```python
   plan.append(
       PlannedOperation(
           src=scanned.path,
           dst=dst,
           action=self.settings.general.action,
           category=cls_res.category,
           confidence=cls_res.confidence,
           details=cls_res.signals,
           quarantine=cls_res.needs_quarantine,
           quarantine_reason=cls_res.quarantine_reason,
           primary_src=scanned.primary_media_path,
       )
   )
   ```
2. **Synchronized Conflict Resolution in `executor.plan_operations`**:
   Maintain a mapping of `primary_src -> resolved_primary_dst`.
   When resolving sidecar operations, dynamically align their stem to the primary's resolved stem:
   ```python
   primary_dst_resolutions: Dict[Path, Path] = {}
   # During primary operation processing:
   primary_dst_resolutions[item.src] = item.dst

   # During sidecar operation processing:
   if item.primary_src and item.primary_src in primary_dst_resolutions:
       resolved_p_dst = primary_dst_resolutions[item.primary_src]
       if resolved_p_dst.stem != item.dst.stem:
           # Suffix detection (e.g. .en.srt, .forced.srt)
           orig_stem = item.src.stem
           p_stem = item.primary_src.stem
           lang_tag = orig_stem[len(p_stem):] if orig_stem.lower().startswith(p_stem.lower()) else ""
           new_sidecar_name = f"{resolved_p_dst.stem}{lang_tag}{item.dst.suffix}"
           item.dst = resolved_p_dst.parent / new_sidecar_name
   ```
3. **Co-located Sequential Execution**:
   In `build_plan`, sort operations so that companion files immediately follow their primary video file:
   `[Primary A, Companion A1, Companion A2, Primary B, Companion B1, ...]`.
   If a primary file move fails or is skipped, immediately mark all its paired companions as `FAILED` or `SKIPPED`.

---

### 3.3 Folder Cleanup Logic & Empty Directory Removal Safety

#### Safety Audit of `executor.py:clean_empty_directories`
Lines 610–689 of `src/media_sorter/executor.py` implement directory cleanup:
```python
def clean_empty_directories(self, moved_src_paths: List[Path]) -> int:
    source_roots = {p.resolve() for p in self.settings.get_source_paths()}
    candidate_dirs: Set[Path] = set()
    for src in moved_src_paths:
        ...
        parent = src.resolve().parent
        while parent not in source_roots and any(parent.is_relative_to(root) for root in source_roots):
            candidate_dirs.add(parent)
            parent = parent.parent
```
- **Verified Invariants**:
  1. `source_roots` containment check: `while parent not in source_roots and any(parent.is_relative_to(root) for root in source_roots)` guarantees candidate directories never include the configured root downloads folder.
  2. Guard against configured roots: `if d in source_roots: continue`.
  3. Deepest-first sorting: `sorted(candidate_dirs, key=lambda d: len(d.parts), reverse=True)` guarantees subfolders (e.g. `Release/Subs`) are deleted before their parents (`Release`).
  4. Non-empty directory protection: `entries = [e for e in d.iterdir() if e.name not in (".DS_Store", "Thumbs.db", "desktop.ini") and not e.name.lower().endswith(".txt")]`. If any video or non-junk file remains, the directory is preserved.
  5. Tested behavior: `tests/unit/test_executor_and_rollback.py::test_cleanup_deletes_txt_files_and_removes_dirs` verifies that companion `.txt` and empty directories are cleaned while the root directory is kept intact.

#### Cleanup Enhancements
- In `clean_empty_directories`, companion `.txt` files (e.g. `Movie.txt`, `README.txt`) are unlinked. Ensure unlinking handles `PermissionError` and `FileNotFoundError` without halting the cleanup loop.
- After a live rollback, empty destination directories (e.g. `Movies/Movie (2024)/`) should be pruned using the same safe bottom-up traversal.

---

### 3.4 Folder Explorer Exclusions: `.txt` and `.srt` Verification

#### Verification of Server Filtering
In `src/media_sorter/server.py`:
1. `list_files_in_dir(directory: Path)` (line 129):
   ```python
   for root, _, files in os.walk(directory):
       for f in files:
           if f.lower().endswith((".txt", ".srt")):
               continue
   ```
2. `inspect_downloads_folder(directory: Path, ...)` (line 453):
   ```python
   for root, _, files in os.walk(directory):
       for f in files:
           if f.lower().endswith((".txt", ".srt")):
               continue
   ```
- Both filtering loops case-insensitively exclude `.txt` and `.srt` files across all views:
  - `files`: General directory file list
  - `shows[].files`: Detected show episodes
  - `unsure_groups[].files`: Unsure clustered groups
  - `singles`: Unsure individual files
- Verified via automated unit tests:
  - `tests/unit/test_server_and_env.py::test_folder_explorer_excludes_txt_files` (PASS)
  - `tests/unit/test_server_and_env.py::test_folder_explorer_excludes_srt_files` (PASS)

#### Single-File Delete Caveat
In `server.py:817-869` (`delete_download_file`):
When a media file is deleted via `/api/files/download`, it unlinks `companion_txt = target.with_suffix(".txt")`.
However, `.srt` files are hidden from the Folder Explorer UI. If a user deletes a video file from the web UI, its companion `.srt` file was not unlinked, leaving an orphan `.srt` file that prevents the parent directory from being removed.
- **Recommended Fix in `delete_download_file`**:
  Also unlink companion subtitles:
  ```python
  for sub_ext in (".srt", ".sub", ".ass", ".nfo"):
      comp = target.with_suffix(sub_ext)
      if comp.is_file() and comp != target:
          try:
              comp.unlink()
          except Exception:
              pass
  ```

---

## 4. Deep-Dive Investigation: Input Sanitization & Security Guardrails

### 4.1 Filename Sanitization in `/api/files/manual-sort`

#### Vulnerability Analysis
In `src/media_sorter/server.py:1086-1144`:
```python
@app.post("/api/files/manual-sort")
def manual_sort_file(req: ManualSortRequest):
    ...
    if category == "movie":
        movie_title = req.title.strip()
        ...
        folder_name = f"{movie_title} ({year})" if year else movie_title
        dest_dir = movies_base / folder_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        final_dst = dest_dir / f"{folder_name}{target.suffix}"
    elif category == "tv":
        show_name = req.title.strip()
        ...
        dest_dir = shows_base / show_name / f"Season {season:02d}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        final_dst = dest_dir / f"{show_name} - S{season:02d}E{episode:02d}{target.suffix}"
```
- **Security Deficiencies**:
  1. `req.title` is unvalidated and unescaped.
  2. If `req.title` contains `/` or `../` (e.g. `../../etc/cron.d`), `dest_dir` traverses outside `movies_base` or `shows_base`, allowing arbitrary directory creation and file movement across the filesystem.
  3. If `req.title` contains cross-platform forbidden characters (`: * ? " < > | \`), moving to NTFS, exFAT, or Samba network shares causes OS I/O failures.
  4. If `req.title` contains Windows reserved names (`CON`, `PRN`, `AUX`, `NUL`, etc.), filesystem creation fails on Windows hosts.

#### Concrete Implementation Blueprint
Utilize `sanitize_filename_component` from `media_sorter.namer` and enforce storage containment:
```python
from media_sorter.namer import sanitize_filename_component

@app.post("/api/files/manual-sort")
def manual_sort_file(req: ManualSortRequest):
    downloads_path = (settings.get_source_paths()[0] if settings.get_source_paths() else Path("downloads")).resolve()
    target = (downloads_path / req.relative_path).resolve()
    if not target.is_relative_to(downloads_path) or not target.is_file():
        # Fallback search by filename only within downloads_path
        found = None
        for root, _, files in os.walk(downloads_path):
            if req.relative_path in files or target.name in files:
                candidate = Path(root) / (req.relative_path if req.relative_path in files else target.name)
                if candidate.is_relative_to(downloads_path) and candidate.is_file():
                    found = candidate
                    break
        if found:
            target = found
        else:
            raise HTTPException(status_code=404, detail="File not found")

    category = req.category.lower()
    raw_title = req.title.strip()
    clean_title = sanitize_filename_component(raw_title)
    if not clean_title or clean_title == "unnamed":
        raise HTTPException(status_code=400, detail="Invalid title: contains only forbidden characters")

    if category == "movie":
        movies_base = settings.get_destination_path("movie").resolve()
        year = req.year
        y_m = re.search(r"\((19\d\d|20\d\d)\)", clean_title)
        if y_m and not year:
            year = int(y_m.group(1))
            clean_title = re.sub(r"\s*\(\d{4}\)", "", clean_title).strip(" .-")
        
        folder_name = f"{clean_title} ({year})" if year else clean_title
        folder_name = sanitize_filename_component(folder_name)
        dest_dir = (movies_base / folder_name).resolve()
        
        # Containment assertion against directory traversal
        if not dest_dir.is_relative_to(movies_base):
            raise HTTPException(status_code=400, detail="Directory traversal detected in movie destination")
        
        dest_dir.mkdir(parents=True, exist_ok=True)
        final_dst = dest_dir / f"{folder_name}{target.suffix}"

    elif category == "tv":
        shows_base = settings.get_destination_path("tv").resolve()
        season = max(0, req.season) if req.season is not None else 1
        episode = max(0, req.episode) if req.episode is not None else 1
        dest_dir = (shows_base / clean_title / f"Season {season:02d}").resolve()
        
        if not dest_dir.is_relative_to(shows_base):
            raise HTTPException(status_code=400, detail="Directory traversal detected in show destination")
        
        dest_dir.mkdir(parents=True, exist_ok=True)
        file_name = sanitize_filename_component(f"{clean_title} - S{season:02d}E{episode:02d}{target.suffix}")
        final_dst = dest_dir / file_name

    else:
        dest_base = settings.get_destination_path(category).resolve()
        dest_dir = dest_base
        dest_dir.mkdir(parents=True, exist_ok=True)
        final_dst = dest_dir / sanitize_filename_component(target.name)
        if not final_dst.resolve().is_relative_to(dest_base):
            raise HTTPException(status_code=400, detail="Invalid destination path")
```

---

### 4.2 Windows Reserved Device Names

#### Rules & Invariance
Windows strictly prohibits the following base device names regardless of file extension:
`CON`, `PRN`, `AUX`, `NUL`, `COM1`, `COM2`, `COM3`, `COM4`, `COM5`, `COM6`, `COM7`, `COM8`, `COM9`, `LPT1`, `LPT2`, `LPT3`, `LPT4`, `LPT5`, `LPT6`, `LPT7`, `LPT8`, `LPT9`.
- Creating `CON.mp4` on Windows fails with `WinError 87`.
- Creating folder `AUX` fails.

#### Implementation in `sanitize_filename_component`
In `namer.py:48-52`:
```python
upper_base = clean.split(".")[0].upper()
if upper_base in RESERVED_NAMES:
    clean = f"_{clean}"
```
- For filename `CON.mp4`: `clean.split(".")[0]` is `"CON"` → becomes `"_CON.mp4"`.
- For folder `AUX`: `clean.split(".")[0]` is `"AUX"` → becomes `"_AUX"`.
- For `com1.mkv`: `clean.split(".")[0]` is `"COM1"` → becomes `"_com1.mkv"`.

All endpoints that build directories or filenames from user input (`manual_sort_file`, `_do_resolve_item`, `sort_group_endpoint`) must pass all path components through this function.

---

### 4.3 Storage Boundary Checks in `/api/poster/local`

#### Vulnerability Analysis
In `src/media_sorter/server.py:1443-1452`:
```python
@app.get("/api/poster/local")
def serve_local_poster(path: str):
    """Serve a local show artwork image securely."""
    p = Path(path).resolve()
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="Poster file not found")
    if p.suffix.lower() not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        raise HTTPException(status_code=400, detail="Not an image file")
    return FileResponse(p)
```
- **Vulnerability**: Any client can query `/api/poster/local?path=/path/to/private/image.png`. It bypasses all directory isolation and serves files from anywhere on the host filesystem.

#### Secure Storage Boundary Implementation
```python
@app.get("/api/poster/local")
def serve_local_poster(path: str):
    """Serve a local show artwork image securely within configured storage roots."""
    try:
        p = Path(path).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed file path")

    # 1. Enforce file extension allowlist
    if p.suffix.lower() not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        raise HTTPException(status_code=400, detail="Not an image file")

    # 2. Gather all authorized storage boundaries from settings
    allowed_roots: List[Path] = []
    for src in settings.get_source_paths():
        try:
            allowed_roots.append(src.resolve())
        except Exception:
            pass

    for category in (
        "movie", "tv", "anime", "quarantine", "music",
        "audiobook", "podcast", "photo", "home_video", "documentary"
    ):
        try:
            allowed_roots.append(settings.get_destination_path(category).resolve())
        except Exception:
            pass

    # 3. Verify containment
    is_contained = any(p == root or p.is_relative_to(root) for root in allowed_roots)
    if not is_contained:
        logger.warning("Path traversal attempt blocked in /api/poster/local", path=str(p))
        raise HTTPException(
            status_code=403,
            detail="Access denied: path is outside configured media storage directories"
        )

    # 4. Check existence and serve
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="Poster file not found")

    return FileResponse(p)
```

---

## 5. Deep-Dive Investigation: Database & Transaction Scoping

### 5.1 SQLite WAL Concurrency and Session Scoping in `db.py`

#### The `scoped_session` Re-instantiation Defect
In `src/media_sorter/db.py:59-77`:
```python
def get_session_factory(engine: Engine) -> scoped_session[Session]:
    """Create a scoped session factory bound to the given engine."""
    return scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

@contextmanager
def get_db_session(engine: Engine) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    session_factory = get_session_factory(engine)
    session: Session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```
- **Architectural Defects**:
  1. Every call to `get_db_session(engine)` executes `get_session_factory(engine)`, which creates a brand new `scoped_session` registry instance. This completely destroys the caching and thread-local scoping benefits of SQLAlchemy's `scoped_session`.
  2. In `finally`, `session.close()` is called, but `session_factory.remove()` is never called. The thread-local registry inside the transient `scoped_session` is abandoned, leaking connections and memory under high-throughput concurrent requests.

#### Thread-Safe Engine-Cached Session Factory Architecture
```python
from typing import Dict
from sqlalchemy.orm import scoped_session, sessionmaker, Session

_ENGINE_SESSION_FACTORIES: Dict[Engine, scoped_session[Session]] = {}

def get_session_factory(engine: Engine) -> scoped_session[Session]:
    """Retrieve or create a persistent scoped session factory bound to the engine."""
    if engine not in _ENGINE_SESSION_FACTORIES:
        _ENGINE_SESSION_FACTORIES[engine] = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=engine)
        )
    return _ENGINE_SESSION_FACTORIES[engine]

@contextmanager
def get_db_session(engine: Engine) -> Generator[Session, None, None]:
    """Provide a transactional scope with clean commit/rollback and connection pool release."""
    factory = get_session_factory(engine)
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        factory.remove()  # Clean up thread-local registry and return connection to pool
```

#### SQLite WAL Mode and Concurrency Tuning
In `get_engine()` (`db.py:23-48`), the SQLite connection events configure:
- `PRAGMA foreign_keys=ON`
- `PRAGMA journal_mode=WAL` (Write-Ahead Logging allows concurrent readers alongside a single writer)
- `PRAGMA synchronous=NORMAL` (optimal performance with WAL mode)
- `PRAGMA busy_timeout=30000` (increase from 10000ms to 30000ms to eliminate `sqlite3.OperationalError: database is locked` during concurrent background auto-sort and web requests)

---

### 5.2 Rollback Mechanics & Batch History Tracking in `executor.py`

#### Vulnerabilities in Existing Rollback
In `executor.py:519-575`:
```python
def rollback_batch(self, batch_id: Optional[str] = None) -> int:
    ...
    ops = (
        self.session.query(Operation)
        .filter_by(batch_id=batch.id, status=OperationStatus.COMMITTED.value)
        .order_by(Operation.id.desc())
        .all()
    )

    reverted_count = 0
    for op in ops:
        src = Path(op.src)
        dst = Path(op.dst)
        action = op.action
        try:
            if action == ActionType.MOVE.value:
                if dst.exists():
                    src.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(dst, src)
                    reverted_count += 1
...
    batch.status = "ROLLED_BACK"
    self.session.commit()
    return reverted_count
```
- **Defects Identified**:
  1. **Partial Rollback Failure State**:
     If an operation fails inside the loop (e.g. `OSError`), it logs an error and continues. At the end of the method, `batch.status = "ROLLED_BACK"` is unconditionally written to the database. The system falsely claims the batch is fully reverted, permanently leaving orphaned files without recourse.
     **Fix**: Count `failed_count`. If `failed_count > 0`, set `batch.status = "PARTIAL_ROLLBACK"` (or `"FAILED"` if reverted == 0). Only mark `"ROLLED_BACK"` if all operations reverted.
  2. **Cross-Filesystem Rollback Crash (`os.replace`)**:
     `os.replace(dst, src)` throws `Invalid cross-device link` (`EXDEV`) when `src` (e.g. `/md0/jdownloads`) and `dst` (e.g. `/tmp/test_dir` or secondary mount) reside on different filesystems or mount points.
     **Fix**: Use `self._safe_move(dst, src)`.
  3. **Database State De-synchronization**:
     - `FileRecord`: During sort, `FileRecord.status` is set to `"organized"` at `dst`. Rollback moves the file back to `src`, but leaves the stale `FileRecord` at `dst`! Future scans may misread file history.
       **Fix**: Delete `FileRecord` for `dst` upon rollback and update or clear the record for `src`.
     - `LibraryItem.item_count`: When operations are rolled back, `LibraryItem.item_count` remains inflated.
       **Fix**: Decrement `LibraryItem.item_count` by the number of reverted operations for that item.
  4. **Orphaned Destination Directories**:
     When moving files back to source directories, empty folders remain in `Movies/` and `TV Shows/`.
     **Fix**: Prune empty parent folders in the destination tree back up to the library destination root.

#### Hardened `rollback_batch` Implementation Blueprint
```python
def rollback_batch(self, batch_id: Optional[str] = None) -> int:
    """Invert all COMMITTED operations in a batch with transactional safety and catalog updates."""
    query = self.session.query(BatchRecord)
    if batch_id:
        batch = query.filter_by(id=batch_id).first()
    else:
        batch = query.filter(
            BatchRecord.status.in_(["COMPLETED", "PARTIAL_FAILURE"]),
            BatchRecord.dry_run == False
        ).order_by(BatchRecord.created_at.desc()).first()

    if not batch:
        logger.warning("No qualifying batch found for rollback", requested_id=batch_id)
        return 0

    logger.info("Initiating rollback", batch_id=batch.id)
    ops = (
        self.session.query(Operation)
        .filter_by(batch_id=batch.id, status=OperationStatus.COMMITTED.value)
        .order_by(Operation.id.desc())
        .all()
    )

    reverted_count = 0
    failed_count = 0
    reverted_dest_dirs: Set[Path] = set()

    for op in ops:
        src = Path(op.src)
        dst = Path(op.dst)
        action = op.action

        try:
            if action == ActionType.MOVE.value:
                if dst.exists():
                    src.parent.mkdir(parents=True, exist_ok=True)
                    # Use cross-device safe move rather than bare os.replace
                    self._safe_move(dst, src)
                    reverted_count += 1
                    reverted_dest_dirs.add(dst.parent)

                # Restore backup if one was taken
                if op.backup_path and Path(op.backup_path).exists():
                    self._safe_move(Path(op.backup_path), dst)

            elif action == ActionType.COPY.value:
                if dst.exists():
                    dst.unlink()
                    reverted_count += 1
                    reverted_dest_dirs.add(dst.parent)

            elif action in (ActionType.LINK.value, ActionType.HARDLINK.value):
                if dst.exists() or dst.is_symlink():
                    dst.unlink()
                    reverted_count += 1
                    reverted_dest_dirs.add(dst.parent)

            op.status = OperationStatus.ROLLED_BACK.value

            # Clean FileRecord for destination
            rec = self.session.query(FileRecord).filter_by(path=str(dst)).first()
            if rec:
                self.session.delete(rec)

        except Exception as e:
            failed_count += 1
            logger.error("Error reverting operation during rollback", op_id=op.id, error=str(e))

    # Accurate batch status assignment
    if failed_count == 0 and reverted_count > 0:
        batch.status = "ROLLED_BACK"
    elif reverted_count > 0:
        batch.status = "PARTIAL_ROLLBACK"
    else:
        batch.status = "ROLLBACK_FAILED"

    self.session.commit()

    # Clean up empty directories in destination tree
    self._clean_empty_destination_dirs(reverted_dest_dirs)

    # Decrement LibraryItem counts
    self._decrement_library_counts(ops)

    return reverted_count
```

---

### 5.3 Concurrency Locking Across Sort Runs, Rollbacks, and Background Tasks

#### The Missing Lock Problem
In the current codebase:
- `MediaSorterApp.run()` acquires `acquire_process_lock(lock_path)`.
- **Zero other operations acquire the lock**:
  - `MediaSorterApp.rollback()`: Unlocked.
  - `MediaSorterApp.rollback_all()`: Unlocked.
  - `server.py::manual_sort_file`: Unlocked.
  - `quarantine.py::undo_item`: Unlocked.
- **Async Event Loop Blocking**:
  In `server.py:598-608` (`auto_sort_worker`):
  ```python
  sorter = MediaSorterApp(settings, engine)
  sorter.run()  # Synchronous CPU & I/O heavy operation directly blocks async event loop!
  ```

#### Unified Cross-Process & In-Process Concurrency Control
1. **Combine Process File Lock with In-Memory RLock**:
   ```python
   import threading
   from contextlib import contextmanager

   _PROCESS_LOCK = threading.RLock()

   @contextmanager
   def acquire_media_sorter_lock(lock_file_path: Path):
       """Dual-layer thread and process mutual exclusion."""
       with _PROCESS_LOCK:
           with acquire_process_lock(lock_file_path):
               yield
   ```
2. **Locking Rollback Operations**:
   In `sorter.py`:
   ```python
   def rollback(self, batch_id: Optional[str] = None) -> int:
       lock_path = self.settings.get_database_path().with_suffix(".lock")
       with acquire_process_lock(lock_path):
           with get_db_session(self.engine) as session:
               executor = MediaExecutor(self.settings, session)
               return executor.rollback_batch(batch_id)

   def rollback_all(self) -> int:
       lock_path = self.settings.get_database_path().with_suffix(".lock")
       with acquire_process_lock(lock_path):
           with get_db_session(self.engine) as session:
               executor = MediaExecutor(self.settings, session)
               return executor.rollback_all()
   ```
3. **Offloading Auto-Sort Worker**:
   In `server.py`:
   ```python
   async def auto_sort_worker():
       while True:
           interval = settings.general.scan_interval_seconds
           if interval > 0:
               try:
                   sorter = MediaSorterApp(settings, engine)
                   await asyncio.to_thread(sorter.run)
               except ProcessLockError:
                   logger.debug("Auto-sort skipped: another operation holds the execution lock")
               except Exception as e:
                   logger.error("Auto-sort background task error", error=str(e))
           await asyncio.sleep(max(interval, 10) if interval > 0 else 10)
   ```
4. **FastAPI HTTP 409 Conflict Handling**:
   In `server.py`, wrap `trigger_run`, `trigger_rollback`, `trigger_rollback_all`, and `manual_sort_file` to catch `ProcessLockError` and return `HTTPException(status_code=409, detail="Another operation is currently locking the media library")`.

---

## 6. Synthesis & Proposed Architecture Blueprints

| Component | Target File | Proposed Structural Enhancement | Rationale |
|---|---|---|---|
| **Sidecar Pairing** | `src/media_sorter/scanner.py` | Order candidates by stem length descending; verify boundary delimiter (`.`, `-`, `_`, ` `); handle `Subs/` subfolders; allow generic single-video directory fallback. | Prevents prefix collision (e.g. `Show - 10.srt` pairing with `Show - 1.mkv`), pairs nested subtitle tracks, and pairs NFO/poster in single-video folders. |
| **Atomic Companion Moves** | `src/media_sorter/sorter.py`<br>`src/media_sorter/executor.py` | Add `primary_src` link to `PlannedOperation`; dynamically re-target companion destination when primary encounters conflict resolution. | Ensures subtitles move with video if primary is renamed to `(1)` or redirected; aborts companion moves if primary fails. |
| **Input Sanitization** | `src/media_sorter/server.py` | Sanitize `req.title` using `sanitize_filename_component`; enforce `dest_dir.is_relative_to(base)`. | Prevents path traversal via `../../` and avoids filesystem write errors on NTFS/SMB from illegal characters `: * ? " < > \|`. |
| **Windows Reserved Devices** | `src/media_sorter/server.py`<br>`src/media_sorter/namer.py` | Ensure `CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9` are prefixed with `_` in all manual endpoints. | Prevents severe OS errors on Windows file servers. |
| **Storage Boundary Checks** | `src/media_sorter/server.py` | Verify requested poster path in `/api/poster/local` resolves strictly within `settings.get_source_paths()` or destination paths. | Closes arbitrary local file read vulnerability (HTTP 403 Forbidden). |
| **Session Scoping & Pooling** | `src/media_sorter/db.py` | Cache `scoped_session` factory per engine; invoke `factory.remove()` in `finally` block of `get_db_session`. | Eliminates `scoped_session` re-instantiation, returns connections to `QueuePool`, prevents connection exhaustion. |
| **Rollback Integrity** | `src/media_sorter/executor.py` | Set `batch.status = "PARTIAL_ROLLBACK"` on partial failures; use `_safe_move` for cross-device links; delete stale `FileRecord`; decrement `LibraryItem.item_count`. | Ensures transactional truth in batch status, prevents crash on multi-disk setups, maintains library catalog accuracy. |
| **Concurrency Locking** | `src/media_sorter/sorter.py`<br>`src/media_sorter/server.py` | Wrap `rollback` and `rollback_all` in `acquire_process_lock`; offload `sorter.run()` in `auto_sort_worker` via `asyncio.to_thread`. | Prevents concurrent sort vs rollback race conditions and eliminates event loop thread freezing. |

---

## 7. Verification & Testing Strategy

To verify the implementation of these enhancements without mutating production directories, an isolated unit test suite should be executed:

```bash
.venv/bin/pytest tests/unit/test_executor_and_rollback.py tests/unit/test_server_and_env.py tests/unit/test_config_and_db.py -v
```

### Proposed Test Scenarios to Implement in Unit Suite
1. **Sidecar Pairing Disambiguation**:
   - Create `Show - 1.mkv`, `Show - 10.mkv`, and `Show - 10.srt`. Verify `Show - 10.srt` pairs with `Show - 10.mkv`, not `Show - 1.mkv`.
   - Create `Movie/Subs/en.srt` and `Movie/Movie.mkv`. Verify `en.srt` is paired with `Movie.mkv`.
2. **Atomic Move on Conflict**:
   - Pre-populate destination with `Avatar (2009).mkv`.
   - Process incoming `Avatar (2009).mkv` and `Avatar (2009).en.srt`.
   - Under `ConflictPolicy.RENAME_UNIQUE`, verify video moves to `Avatar (2009) (1).mkv` AND subtitle moves to `Avatar (2009) (1).en.srt`.
3. **Manual Sort Sanitization**:
   - Call `POST /api/files/manual-sort` with title `"Star Wars: Episode IV *Special* <Cut>"`.
   - Verify created directory and filename are sanitized without `: * < >`.
   - Call with title `"../../etc/cron"`. Verify HTTP 400 is returned.
   - Call with title `"CON"`. Verify folder and file are named `_CON`.
4. **Local Poster Path Traversal**:
   - Call `GET /api/poster/local?path=/etc/passwd` → HTTP 400 (not image).
   - Call `GET /api/poster/local?path=/root/secret.png` → HTTP 403 (outside storage boundary).
   - Call with image inside `downloads/` or `movies/` → HTTP 200.
5. **Partial Rollback Batch Status**:
   - Simulate a failed reverse move during rollback.
   - Verify `BatchRecord.status` is marked `"PARTIAL_ROLLBACK"`, not `"ROLLED_BACK"`.
6. **Scoped Session Registry Cleanup**:
   - Call `get_db_session` in a loop across multiple threads.
   - Verify `scoped_session.registry.has()` is cleared and connection pool handles are returned.
7. **Concurrency Lock on Rollback**:
   - Hold lock with `acquire_process_lock`.
   - Attempt `sorter.rollback()`.
   - Verify `ProcessLockError` is raised.

---
*Report compiled and verified by `teamwork_preview_explorer_m2_3` on 2026-09-06.*
