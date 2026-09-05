# Changelog

All notable changes to the Media Sorter project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.5] - 2026-09-05

### Added
- **Quarantine Top Action Buttons & Bulk Controls**:
  - Action buttons at the top of the Review & Quarantine header for immediate manual actions: `🎬 Move to Movies`, `📺 Move to Shows`, `✏️ Set Show/Movie`, `↩️ Unflag`, and `↩️ Undo All Resolved`.
  - Multi-item selection checkboxes with header `Select All` / `Deselect All` toggle and live selection count tracking.
  - Selection toolbar that adapts dynamically based on checked items for bulk execution.
  - Backend bulk endpoints:
    - `POST /api/quarantine/bulk-resolve`: Bulk moves selected or all pending quarantine items to Movies or TV Shows inside a fast transaction.
    - `POST /api/quarantine/bulk-undo`: Bulk unflags pending items or rollbacks all resolved quarantine files back to original source directories.
- **Manual Modal File Switcher**:
  - Added file picker dropdown inside `modal-manual-sort` when multiple quarantine items are available, enabling switching between items without reopening the modal.
- **Granular & Global Undo Actions**:
  - Added `↩️ Undo All Resolved` button to easily restore all resolved quarantine files to their source folders.
  - Per-item unflagging for pending items and per-item rollback for resolved items.

### Fixed
- **False-Positive TV Show Classifications for Movies**:
  - **Resolution Dimensions**: Filenames containing dimensions like `1920x1080` or `1280x720` no longer falsely match episodic TV season/episode regex (`20x108`, `80x720`). Added negative lookbehind/lookahead and resolution fallback parser `RE_DIMENSIONS`.
  - **Release Years in Torrent Tags**: Anime release regex pattern no longer treats 4-digit release years (1900–2099) in bracketed torrent tags (e.g., `[YTS.MX] Movie Title - 2024 [1080p].mkv`) as episode numbers.
  - **Broad Substring Match**: Replaced broad `"tv" in path_str` check with directory boundary regex `(?i)[/\\](?:tv[/\\]|tv[-_\s]shows?|tv[-_\s]series|season[-_\s]*\d+)`, preventing movies with `HDTV`, `[rartv]`, or `Apple.TV` from routing to TV show logic.
  - **Folder Explorer Subdirectories**: Fixed downloads inspector so scene/torrent movie subfolders (e.g. `The.Dark.Knight.2008.1080p.BluRay/`) are not misidentified as TV show names; movies now properly appear under `singles` targeting `MOVIES_DIR`.
  - **Release Group Cleaning**: Updated `_clean_title` to cleanly strip leading bracketed group tags (e.g., `[YTS.MX]`, `[rarbg]`, `[TGx]`).
- **`.txt` Companion Cleaning & Explorer Filter**:
  - Excluded `.txt` companions (e.g., torrent notes, RARBG.txt) from the folder explorer.
  - Automatically cleans up companion `.txt` files and empty parent release folders when media files are deleted or organized.
- **Safe Quarantine Mode**:
  - Flagged files with confidence below threshold remain in place safely rather than being automatically moved.
- **Missing Module Import**:
  - Fixed missing `import re` in `src/media_sorter/classifier.py`.

### Changed
- Unified Settings and `.env` configuration into a single coherent dashboard tab.
- Expanded automated test suite to 65 tests covering movie dimension tokenization, bracketed release years, HDTV classification, folder explorer movie detection, and bulk quarantine APIs.

---

## [1.0.4] - 2026-09-05

### Added
- File renaming toggle (`RENAME_FILES`) and customizable naming templates for movies and TV shows (`MOVIE_TEMPLATE`, `TV_TEMPLATE`).
- Automatic cleanup of empty parent directories after files are moved (`CLEANUP_EMPTY_DIRS`).

---

## [1.0.3] - 2026-09-05

### Added
- TV show dropdown aggregation in downloads folder explorer with collapsible season groups.
- Local artwork and TVmaze poster lookup for series.

---

## [1.0.2] - 2026-09-05

### Added
- Instant batch rollbacks and transactional operation journaling.
- Manual file categorization modal and REST API endpoints.

---

## [1.0.1] - 2026-09-05

### Added
- Multi-signal classifier supporting audiobooks, podcasts, home videos, and archives.
- SQLite WAL operation journaling.

---

## [1.0.0] - 2026-09-05

### Added
- Initial release with atomic file sorting, dry-run simulation, and web dashboard.
