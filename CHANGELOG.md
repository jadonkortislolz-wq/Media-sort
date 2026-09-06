# Changelog

All notable changes to the Media Sorter project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.7] - 2026-09-05

### Added
- **Library Catalog & Show/Movie Management (`📚 Library`)**:
  - Added a dedicated top-level **📚 Library** view with full catalog tracking of all indexed shows and movies across storage drives.
  - Interactive selector buttons to switch between **📺 Shows**, **🎬 Movies**, and **📂 All**, with live count badges.
  - Real-time instant search input to filter titles as you type.
  - Disk scanning synchronization (`POST /api/library/rescan`) that indexes directory trees, episode counts, seasons, and technical metadata.
  - Persistent database tracking via `LibraryItem` table model with unique constraint protection and last-updated tracking.
- **Automatic Show Memory Routing**:
  - Whenever a new show is detected or sorted, it is automatically cataloged in the Library.
  - When inspecting downloads or analyzing files, media sorter queries known shows from the library and automatically routes incoming media (such as extras, behind-the-scenes, specials, and unbracketed files) into that show's folder (`SHOWS_DIR / <Show Name>`).
- **Unsure File Grouping Dropdowns**:
  - Automatically clusters non-show files into dedicated collapsible dropdown cards instead of dumping them into a flat singles list:
    - **Shared Subfolder Groups**: Files sharing a common subfolder in downloads form their own group card (e.g. `📁 Shared Subfolder: Dexter Extras (5 files)`).
    - **Matching Name Prefix Groups**: Files sharing a common clean title stem or prefix form their own group card (e.g. `🏷️ Matching Name Prefix: Blood, Guts and Body Parts (2 files)`).
    - Only truly lone, isolated files remain in the singles media list.
  - Group action buttons:
    - `⚡ Sort Group`: Sorts all files in the group directly via `POST /api/files/sort-group`.
    - `✏️ Set Show/Movie for Group`: Opens the manual assignment modal for the entire group, allowing one-click bulk categorization to Movies or TV Shows.
- **Group Sorting Endpoint (`POST /api/files/sort-group`)**:
  - Server endpoint that batch-processes unsure groups of files with show name override or movie destination formatting, atomic movement, and automatic library catalog registration.

### Fixed
- **Anime Fansub Adjacent Brackets Regex**:
  - Fixed `RE_ANIME_RELEASE` regex to support adjacent bracket tags without spaces (e.g. `[Erai-raws] Bleach - 001 [1080p][MultiSub][EF0AF7BA].mkv`), ensuring anime episode fan releases are accurately classified.
- **Prevent Anime Episode Matching into SxxExx**:
  - Added negative lookahead `(?![xX\w])` to prevent episodic titles like `Game of Thrones - 1x09 - Baelor` from prematurely matching `1` as an anime episode instead of `Season 1 Episode 9`.
- **Fast Local Artwork & Responsive Downloads Inspection**:
  - Updated `fetch_show_poster` with `allow_network=False` during folder inspection so downloads scanning completes in under 2 seconds rather than stalling on synchronous external network queries.

## [1.0.6] - 2026-09-05

### Added
- **Targeted Show Sorting (`POST /api/files/sort-show`)**:
  - The "⚡ Sort Now" button inside any show's dropdown card in the Downloads Folder Explorer now targets that specific show directly.
  - Sorts all episodes of that show into `SHOWS_DIR / <Show Name> / Season XX / ...` with full transaction tracking, database history, and instant rollback support.
  - Interactive UI with button loading spinner (`<span class="loading-spinner"></span> Sorting...`), disabled state during execution, success toast with count of sorted episodes, and automatic UI refresh.
- **Standalone Episode Pattern Recognition**:
  - Added support for standalone `Episode \d{1,4}` and `Ep \d{1,4}` patterns (e.g., `Naruto Episode 207 The Supposed Sealed Ability.mkv`, `Bleach Episode 05.mkv`).
  - Added support for anime/fansub series formatting without release group prefixes (e.g., `BLEACH꞉ Sennen Kessen-hen - 27 E89717B7].mkv`).
  - Added support for anime opening/ending patterns (`S03ED01`, `S03OP01`).
- **Interactive Button Loading States**:
  - Added loading spinner and disabled state to `⚡ Run Sort Now (Live)`, `⚡ Sort All Files`, and show-specific `⚡ Sort Now` buttons to prevent duplicate runs and give immediate visual feedback.

### Fixed
- **Show "Sort Now" Button Doing Nothing**:
  - Fixed issue where clicking "Sort Now" inside a show dropdown appeared to do nothing because episodic shows like Naruto were failing tokenizer matching, getting classified as low-confidence movies, and being quarantined (which were flagged but not moved).
  - Fixed button calling global sorting instead of targeted show sorting.
  - Fixed run results panel being hidden on Dashboard tab when viewing Folder Explorer tab.
- **MKV Video Containers Misclassified as Audio/Music**:
  - Fixed bug where video containers (`.mkv`, `.mp4`) containing audio streams were routed to audio-only classification if lightweight EBML header parsing didn't match a hardcoded video codec string.
  - Reordered classifier pipeline so video containers and extensions are always checked as videos first before audio-only handling.
  - Expanded EBML video track detection in `_parse_ebml` to recognize generic `V_` track headers (including VC-1, DivX, XviD, and MPEG2).

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
- **Automatic Folder Explorer & Queue Refresh**:
  - Automatically re-scans and refreshes the Downloads Folder Explorer (`loadFiles`) and Quarantine queue (`loadQuarantine`) immediately whenever sorting runs (live or preview) or batch rollbacks complete.
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
## [1.0.8] - 2026-09-06

### Added
- Added missing custom themes: neon-forest, retro-retro, golden-sand, deep-space, candy-cotton.
- Implemented RGB Chroma mode UI with toggle and speed slider, keyframe animations, and persistence via localStorage.
- Added unit tests for theme availability and RGB feature.
