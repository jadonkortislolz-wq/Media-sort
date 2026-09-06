# Handoff Report: Companion File Handling, Input Sanitization, and Database Transaction Hardening

**Agent**: `teamwork_preview_explorer_m2_3` (Explorer Archetype)  
**Parent Agent ID**: `55e25733-b82c-41da-a4ba-b46248b75abb`  
**Date**: 2026-09-06  
**Status**: Complete  
**Report Reference**: `/md0/media-sorter/.agents/teamwork_preview_explorer_m2_3/analysis.md`

---

## 1. Observation

### 1.1 Companion File Pairing & Atomic Move Gaps
- **Sidecar pairing in `src/media_sorter/scanner.py:223-231`**:
  ```python
  for c in candidates:
      c_stem = c.path.stem.lower()
      if s_stem == c_stem or s_stem.startswith(c_stem):
          matched_primary = c
          break
  ```
  `candidates` is unsorted, and `s_stem.startswith(c_stem)` lacks word boundary checks. As a result, `Show - 10.srt` matches `Show - 1.mkv` instead of `Show - 10.mkv`. Subtitles located in `Subs/` or `Subtitles/` subfolders have parent `/Subs` and fail to pair with videos in the release root (`s.primary_media_path` remains `None`).
- **Decoupled conflict resolution in `src/media_sorter/executor.py:163-176` and `sorter.py:159-209`**:
  `MediaSorterApp.build_plan` creates primary operations first, and then sidecar operations based on initial primary destination stems. When `executor.plan_operations` resolves a collision (e.g. `Movie (2024).mkv -> Movie (2024) (1).mkv`), the companion subtitle operation is not updated and remains targeted at `Movie (2024).en.srt`. Under `ConflictPolicy.SKIP`, the video is skipped but the subtitle moves.
- **Folder cleanup in `src/media_sorter/executor.py:610-689`**:
  `clean_empty_directories` safely ascends from moved files up to configured source roots (`source_roots = {p.resolve() for p in self.settings.get_source_paths()}`), deleting `.txt` and junk files (`.DS_Store`, `Thumbs.db`, `desktop.ini`) and pruning empty directories deepest-first. Configured source roots are strictly preserved.
- **Folder Explorer exclusions in `src/media_sorter/server.py:129,453`**:
  Both `list_files_in_dir` and `inspect_downloads_folder` strictly check `if f.lower().endswith((".txt", ".srt")): continue`, cleanly excluding them across all Explorer views.

### 1.2 Input Sanitization & Security Vulnerabilities in `server.py`
- **Manual Sort unescaped input in `server.py:1086-1126`**:
  ```python
  dest_dir = movies_base / folder_name
  final_dst = dest_dir / f"{folder_name}{target.suffix}"
  ```
  `req.title` is raw user input. Forbidden filesystem characters (`: * ? " < > | / \`) and path traversal sequences (`../../`) are unescaped, allowing directory escape from `movies_base` and I/O failures on NTFS/SMB mounts.
- **Windows reserved device names**:
  Titles such as `CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9` are unhandled in `manual_sort_file`, creating illegal device names on Windows hosts (e.g. `CON.mp4`).
- **Arbitrary file disclosure in `server.py:1443-1452` (`/api/poster/local`)**:
  ```python
  @app.get("/api/poster/local")
  def serve_local_poster(path: str):
      p = Path(path).resolve()
      if not p.exists() or not p.is_file(): ...
      if p.suffix.lower() not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]: ...
      return FileResponse(p)
  ```
  `path` is served without checking if it resides within configured downloads or library storage boundaries. Any image file on the host OS is accessible via this endpoint.

### 1.3 Database Scoping, Rollback & Concurrency Defects
- **`scoped_session` re-instantiation in `src/media_sorter/db.py:64-77`**:
  `get_db_session` invokes `get_session_factory(engine)` on every call, instantiating a new `scoped_session` instance every time and never calling `session_factory.remove()`. This leaks database connection objects and thread-local registries.
- **Partial rollback false completion in `src/media_sorter/executor.py:568-574`**:
  In `rollback_batch`, if an operation fails to revert, the error is caught, and `batch.status = "ROLLED_BACK"` is unconditionally written to the database.
- **Cross-device link failure in `executor.py:551`**:
  Rollback uses `os.replace(dst, src)`, which raises `OSError: [Errno 18] Invalid cross-device link` (`EXDEV`) when `src` and `dst` reside on different partitions or mount points.
- **Missing locks during rollback and manual operations**:
  `acquire_process_lock` is only called in `sorter.run()`. It is missing from `sorter.rollback()`, `sorter.rollback_all()`, `/api/files/manual-sort`, and `/api/quarantine/{id}/undo`.
- **Event loop thread blocking**:
  In `server.py:604`, `sorter.run()` is called synchronously inside `auto_sort_worker()`, blocking FastAPI's async event loop.

---

## 2. Logic Chain

1. **Sidecar Pairing & Conflict Alignment**:
   - Because `_pair_sidecars` does not enforce candidate length ordering or boundary delimiters, false prefix matches occur when stem lengths overlap (`Show - 1` vs `Show - 10`). Ordering candidates by length descending and enforcing delimiter boundaries (`.`, `-`, `_`, ` `) guarantees accurate pairing.
   - Because `PlannedOperation` lacks a link between sidecars and their primary files, conflict renames on primary media leave sidecar destinations detached. Adding `primary_src` to `PlannedOperation` allows `plan_operations` to re-align sidecar destination stems to the primary's resolved conflict name (`Movie (1).mkv` → `Movie (1).en.srt`).
2. **Input Sanitization & Storage Containment**:
   - Because `manual_sort_file` builds paths directly from `req.title`, applying `sanitize_filename_component` from `namer.py` strips forbidden characters (`: * ? " < > |`), handles Windows reserved names (`CON.mp4 -> _CON.mp4`), and neutralizes path traversal.
   - Enforcing `dest_dir.is_relative_to(base_dir)` provides defense-in-depth against directory escape.
   - For `/api/poster/local`, computing authorized storage roots (`settings.get_source_paths()` + destination roots) and rejecting paths where `not any(p == root or p.is_relative_to(root))` stops path traversal with HTTP 403 Forbidden.
3. **Database Session Scoping & Concurrency**:
   - Caching the `scoped_session` factory per engine in `db.py` and calling `factory.remove()` in `finally` guarantees that connections return to the `QueuePool` and thread-local state is cleared.
   - Increasing SQLite busy timeout to 30000ms ensures concurrent writes under WAL mode do not encounter lock timeouts.
   - In `rollback_batch`, tracking `failed_count` and assigning `status = "PARTIAL_ROLLBACK"` when `failed_count > 0` preserves accurate batch history.
   - Replacing `os.replace` with `self._safe_move(dst, src)` ensures cross-filesystem rollback resilience.
   - Wrapping `rollback()`, `rollback_all()`, and manual endpoints with `acquire_process_lock` guarantees mutual exclusion, and offloading `sorter.run()` in `auto_sort_worker` via `asyncio.to_thread` prevents event loop blocking.

---

## 3. Caveats

- **Existing Tests**: All 83 unit and integration tests currently pass (`.venv/bin/pytest tests/unit tests/integration`). The proposed changes harden existing behavior without breaking the existing REST API contract or single-page dashboard.
- **Benchmark Suite**: The 63 failures in `tests/benchmark/test_benchmark.py` relate to tokenizer and classifier naming rules, which are concurrently addressed by peer explorer agents `m2_1` and `m2_2`.
- **Read-Only Scope**: In strict accordance with constraints, no source files were modified during this investigation. Detailed replacement blueprints are documented in `analysis.md`.

---

## 4. Conclusion

The investigation successfully identified the root causes and designed comprehensive, non-breaking architectural solutions for all assigned areas:
1. **Sidecar Pairing & Atomicity**: Candidate sorting, delimiter boundary checks, `Subs/` subfolder support, and dynamic sidecar conflict destination re-targeting.
2. **Input Sanitization & Path Traversal Prevention**: Universal `sanitize_filename_component` integration, Windows reserved device name prefixing (`_CON.mp4`), and storage root containment verification in `/api/poster/local` (HTTP 403).
3. **Database & Transaction Scoping**: Engine-cached `scoped_session` with `remove()`, accurate `PARTIAL_ROLLBACK` status, cross-device safe rollback moves, dual-layer mutual exclusion locking, and async worker offloading.

---

## 5. Verification Method

### 5.1 Command Execution
Run unit and integration verification:
```bash
.venv/bin/pytest tests/unit/test_executor_and_rollback.py tests/unit/test_server_and_env.py tests/unit/test_config_and_db.py -v
```

### 5.2 Files to Inspect
- Report: `/md0/media-sorter/.agents/teamwork_preview_explorer_m2_3/analysis.md`
- Target sources examined:
  - `src/media_sorter/scanner.py` (lines 22-28, 206-236)
  - `src/media_sorter/executor.py` (lines 140-178, 519-588, 610-689)
  - `src/media_sorter/server.py` (lines 129, 453, 598-608, 1086-1144, 1443-1452)
  - `src/media_sorter/db.py` (lines 23-77)
  - `src/media_sorter/namer.py` (lines 19-68, 123-157)
  - `src/media_sorter/sorter.py` (lines 159-209, 240-252, 313-324)

### 5.3 Invalidation Conditions
1. If `Show - 10.srt` is paired with `Show - 1.mkv` in a directory containing both `Show - 1.mkv` and `Show - 10.mkv`, the sidecar pairing fix is invalid.
2. If `Movie (2024).mkv` is renamed to `Movie (2024) (1).mkv` under `ConflictPolicy.RENAME_UNIQUE` but its subtitle is placed at `Movie (2024).en.srt`, the atomic companion synchronization is invalid.
3. If `POST /api/files/manual-sort` with title `"Star Wars: Special <Cut>"` or `"../../escaped"` creates an unescaped file or escapes `movies_base`, input sanitization is invalid.
4. If `GET /api/poster/local?path=/etc/passwd` or `/path/outside/storage/image.png` does not return HTTP 400 or HTTP 403, the storage boundary check is invalid.
5. If a simulated failed move in `rollback_batch` marks `batch.status = "ROLLED_BACK"` instead of `"PARTIAL_ROLLBACK"`, the rollback state fix is invalid.
6. If `get_db_session` does not invoke `remove()` or connection handles remain locked across repeated multi-threaded calls, the session lifecycle fix is invalid.
