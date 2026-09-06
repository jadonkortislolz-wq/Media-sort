# Plan: Media Sorter Pattern Matching, Classification & Isolated Benchmark Suite

## Objective
Fulfill Requirements R1, R2, and R3 from the follow-up request:
1. R1: Robust Pattern Matching & Categorization (Movies with release years/editions/multi-part, TV shows SxxExx/season packs/specials/daily/dated, Anime absolute episode numbers/batch tags/resolution tokens, normalization of audio codecs, resolution tags, release groups without loss of title/episode details).
2. R2: Isolated Automated Verification Suite (Repeatable benchmark test suite testing classification, parsing, destination resolution against real-world media filename patterns offline without mutating real media dirs, with clear reporting).
3. R3: Safe Backward Compatibility (Preserve existing UI operations and server API endpoints `/api/files/scan`, `/api/files/sort-show`, `/api/library`).

## Orchestration Strategy
Following the Project Pattern:
1. Phase 0: Survey (Dispatch 3 Explorers)
   - Explorer 1: Tokenizer, Classifier, Namer, and Sorter architecture, existing regexes, missing pattern support (Anime absolute numbering, multi-part movies/specials/daily/dated shows, edition/tag stripping).
   - Explorer 2: Existing test suite, test fixtures, benchmark coverage, and mock filesystem isolation mechanisms.
   - Explorer 3: Server API routes (`/api/files/scan`, `/api/files/sort-show`, `/api/library`), UI interaction endpoints, and regression risks.
2. Phase 1: Assess & Decompose
   - Synthesize Survey reports into `PROJECT.md` with Feature Inventory and Milestones.
   - Setup Dual Tracks: E2E & Benchmark Test Track and Implementation Milestones.
3. Phase 2: Execution via Iteration Loop
   - Milestone 1: Pattern Matching & Classification Engine (Anime absolute numbering, specials, season packs, dated shows, multi-part movies & editions).
   - Milestone 2: Normalization, Tokenizer Cleanups & Destination Routing (Resolution/codec/group normalization without title/episode loss, destination path formatting).
   - Milestone 3: Isolated Benchmark Verification Suite & Test Infrastructure (Offline, diverse real-world filenames, clear pass/fail reporting, zero external network/real filesystem mutation).
   - Milestone 4: API & Endpoint Regression Verification (/api/files/scan, /api/files/sort-show, /api/library).
   - Milestone 5: Final Verification & Adversarial Hardening (100% benchmark pass rate, gate checks with Reviewers, Challengers, and Forensic Auditor).
4. Phase 3: Final Synthesis & Sentinel Report
