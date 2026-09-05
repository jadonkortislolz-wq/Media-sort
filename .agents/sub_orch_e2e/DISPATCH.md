# Dispatch: E2E Testing Track Orchestrator

## Mission
You are the Sub-Orchestrator for the E2E Testing Track.
Your working directory is: /md0/media-sorter/.agents/sub_orch_e2e
Your scope document is: /md0/media-sorter/.agents/sub_orch_e2e/SCOPE.md
Project specification: /md0/media-sorter/PROJECT.md
Authoritative request: /md0/media-sorter/ORIGINAL_REQUEST.md
Your parent is: orchestrator_1 (dd8d62a8-8522-473a-8123-8f8d672e10a1)

## Responsibilities
1. Design E2E test infrastructure and write `TEST_INFRA.md` at `/md0/media-sorter/TEST_INFRA.md`.
2. Follow the 4-tier opaque-box test methodology based on the 10 features in `PROJECT.md § Feature Inventory`:
   - Tier 1: Feature Coverage (≥5 per feature = ≥50 test cases)
   - Tier 2: Boundary & Corner Cases (≥5 per feature = ≥50 test cases)
   - Tier 3: Cross-Feature Combinations (≥10 test cases)
   - Tier 4: Real-World Application Scenarios (≥5 test cases)
   - Total test cases: ≥115 test cases in `tests/e2e/` (e.g. `test_tier1_features.py`, `test_tier2_boundaries.py`, `test_tier3_combinations.py`, `test_tier4_scenarios.py`).
3. Ensure every test runs with isolated mock fixtures / `tmp_path`, with ZERO interaction with real media paths (`/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`).
4. Execute the iteration loop (Explorer / Worker / Reviewer / Auditor) or dispatch `teamwork_preview_test_writer` to author the test suite.
5. Once all tests are written, verify they run cleanly via pytest and publish `/md0/media-sorter/TEST_READY.md`.
6. Send a completion message back to parent orchestrator when `TEST_READY.md` is published.
