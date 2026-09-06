# DISPATCH LOG

## 2026-09-05T23:48:49Z

You are the Project Orchestrator for Media Sorter.

Your working directory is: /md0/media-sorter/.agents/orchestrator_2
The project workspace is: /md0/media-sorter
The authoritative original request is recorded in: /md0/media-sorter/.agents/ORIGINAL_REQUEST.md

Task Summary:
Expand Media Sorter's automated media sorting rules, classification edge-case handling (TV series, Anime, Movies, multi-part episodes, specials, year tags), and build a comprehensive automated test suite and regression benchmark.

Requirements:
1. R1. Robust Pattern Matching & Categorization:
   Expand media classification and destination routing to reliably distinguish between:
   - Movies (including release years, editions, multi-part movies)
   - TV Shows (standard SxxExx, season packs, specials, daily/dated shows)
   - Anime formats (absolute episode numbers, batch tags, resolution tokens)
   Ensure filenames with resolution tags (e.g. 1080p, 4K), audio codecs, release groups, and complex punctuation are accurately normalized without losing episode or title details.

2. R2. Isolated Automated Verification Suite:
   Develop a repeatable test suite testing classification, parsing, and destination resolution against a diverse benchmark dataset of real-world media filename patterns.
   - Tests must run offline without requiring external network connectivity or mutations to real media storage folders.
   - Provide clear reporting on passed, failed, and edge-case classifications.

3. R3. Safe Backward Compatibility:
   Ensure existing UI operations and server API endpoints (/api/files/scan, /api/files/sort-show, /api/library) continue functioning seamlessly with any pattern parser enhancements.

Acceptance Criteria:
- An automated test suite command (e.g., pytest or a test runner script) executes cleanly within the workspace.
- 100% of benchmark test cases pass with zero unhandled exceptions.
- No regression on existing sorting endpoints or file categorization routes.

Operational Instructions:
- Maintain your working files (`plan.md`, `progress.md`, `context.md`) in `/md0/media-sorter/.agents/orchestrator_2/`. Keep `progress.md` updated regularly with current milestones, active tasks, and status.
- Decompose the work, explore the codebase, implement enhancements, verify rigorously with offline isolated tests, and report completion back when all acceptance criteria are met.
- Notify the Sentinel when the mission is completed.
