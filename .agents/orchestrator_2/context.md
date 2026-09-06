# Context: Media Sorter Enhancement

## Background
Media Sorter organizes TV shows, movies, and anime files.
A previous orchestration pass hardened the database layer, session management, and server architecture.
The follow-up request focuses on expanding automated sorting rules, classification edge cases, building an isolated benchmark test suite, and ensuring safe backward compatibility.

## Core Requirements
1. R1: Robust Pattern Matching & Categorization
   - Movies: release years, editions (Director's Cut, Extended, Remastered), multi-part movies (Part 1, CD1, etc.)
   - TV Shows: standard SxxExx, season packs, specials (S00Exx, OVA, SP), daily/dated shows (YYYY-MM-DD or YYYY.MM.DD)
   - Anime formats: absolute episode numbers (e.g. `[SubGroup] Title - 05 [1080p]`), batch tags, resolution tokens
   - Accurate normalization: stripping resolution tags (1080p, 4K, 2160p), audio codecs (AAC, DTS, FLAC), release groups, complex punctuation without losing episode or title details.
2. R2: Isolated Automated Verification Suite
   - Repeatable offline test suite against diverse real-world media filename patterns.
   - Zero external network connectivity, zero mutations to real media storage folders (`/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`, etc.).
   - Clear reporting on passed, failed, and edge-case classifications.
3. R3: Safe Backward Compatibility
   - Existing UI operations and API endpoints (`/api/files/scan`, `/api/files/sort-show`, `/api/library`) continue functioning seamlessly.

## Key Files (Expected)
- `src/media_sorter/tokenizer.py`
- `src/media_sorter/classifier.py`
- `src/media_sorter/namer.py`
- `src/media_sorter/sorter.py`
- `src/media_sorter/scanner.py`
- `src/media_sorter/routes/files.py` (or `server.py`)
- `tests/`
