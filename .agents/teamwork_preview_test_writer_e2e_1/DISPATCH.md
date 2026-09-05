# Dispatch: E2E Test Suite Writer

## Mission
Design and create the requirement-driven, opaque-box E2E test suite for Media Sorter per `PROJECT.md § Feature Inventory` and `ORIGINAL_REQUEST.md`.

## Mandatory Reading
- `/md0/media-sorter/ORIGINAL_REQUEST.md`
- `/md0/media-sorter/PROJECT.md`
- `/md0/media-sorter/.agents/sub_orch_e2e/SCOPE.md`

## Ownership & Files
You own exclusively:
- `/md0/media-sorter/TEST_INFRA.md`
- `/md0/media-sorter/TEST_READY.md`
- `tests/e2e/*` (`tests/e2e/__init__.py`, `tests/e2e/conftest.py`, `tests/e2e/test_tier1_features.py`, `tests/e2e/test_tier2_boundaries.py`, `tests/e2e/test_tier3_combinations.py`, `tests/e2e/test_tier4_scenarios.py`)

## Test Case Requirements (4 Tiers across 10 Features F1-F10)
- **Tier 1: Feature Coverage**: ≥5 tests per feature (F1-F10) = ≥50 test cases in `test_tier1_features.py`. Happy path isolating each feature.
- **Tier 2: Boundary & Corner Cases**: ≥5 tests per feature = ≥50 test cases in `test_tier2_boundaries.py`. Edge cases, invalid inputs, Roman numerals, ambiguous years, anime tags, empty folders, missing files.
- **Tier 3: Cross-Feature Interactions**: ≥10 tests in `test_tier3_combinations.py`. Pairwise interactions (e.g. sort + rollback, sidecars + anime tags, quarantine + resolve, config update + inspection).
- **Tier 4: Real-World Workload Scenarios**: ≥5 end-to-end scenarios in `test_tier4_scenarios.py`. Realistic multi-season downloads, mixed movies/shows/anime with subtitles, bulk manual classification and catalog sync.
- **Total test cases**: ≥115 test cases.

## Critical Constraints
- NEVER touch `/md0/jdownloads`, `/md0/movies1`, or `/md0/tv1`. All tests must use `tmp_path` and isolated mock directories and SQLite databases.
- Run `pytest tests/e2e/` using `/md0/media-sorter/.venv/bin/pytest` to verify all tests execute and pass.
- Write `/md0/media-sorter/TEST_INFRA.md` documenting test architecture and feature coverage matrix.
- Once tests pass, publish `/md0/media-sorter/TEST_READY.md` with test runner commands and coverage summary.
- Write handoff to `/md0/media-sorter/.agents/teamwork_preview_test_writer_e2e_1/handoff.md` and notify orchestrator.

## 2026-09-05T18:53:51Z
You are the E2E Test Suite Writer.
Your working directory is: /md0/media-sorter/.agents/teamwork_preview_test_writer_e2e_1
Your dispatch instructions are at: /md0/media-sorter/.agents/teamwork_preview_test_writer_e2e_1/DISPATCH.md
MANDATORY: Read /md0/media-sorter/ORIGINAL_REQUEST.md and /md0/media-sorter/PROJECT.md before starting work.

Create the opaque-box E2E test suite in tests/e2e/ covering Tiers 1-4 across all 10 features F1-F10 (≥115 tests):
- tests/e2e/test_tier1_features.py (≥50 tests)
- tests/e2e/test_tier2_boundaries.py (≥50 tests)
- tests/e2e/test_tier3_combinations.py (≥10 tests)
- tests/e2e/test_tier4_scenarios.py (≥5 tests)
All tests must use isolated tmp_path fixtures with ZERO touches to /md0/jdownloads, /md0/movies1, /md0/tv1.
Document the test architecture in /md0/media-sorter/TEST_INFRA.md.
Run pytest tests/e2e/ using /md0/media-sorter/.venv/bin/pytest to verify they run.
When complete, publish /md0/media-sorter/TEST_READY.md and deliver your handoff.md. Send completion message when finished.

