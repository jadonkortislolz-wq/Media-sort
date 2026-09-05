# Scope: E2E Testing Track

## Architecture
Opaque-box, requirement-driven end-to-end test suite derived from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory`.
Tests verify external interfaces: REST API routes, CLI, single-page dashboard rendering, sorting runs, rollback behaviors, database state, and isolation safety.

## Feature Inventory (Test Scope)
Covers all 10 features F1-F10:
- F1: Server Architecture & Route Separation
- F2: Dashboard UI, Tabs, Themes, Modals
- F3: REST API 27 Endpoints Backward Compatibility
- F4: Database Session Lifecycle & Connection Pooling
- F5: Transaction Concurrency & Rollback Integrity
- F6: Library Catalog Synchronization & Schema State
- F7: Tokenizer Edge Cases (Roman numerals, ambiguous years, anime parentheses, multi-episodes)
- F8: Input Validation, Path Sanitization, Error Responses
- F9: Companion File Handling, Pairing, Exclusions (.txt, .srt)
- F10: Filesystem Safety & Mock Isolation

## Milestones (E2E Track)
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E-1 | Test Infrastructure & Framework Setup | `TEST_INFRA.md`, test directory layout in `tests/e2e/`, helper fixtures | None | PLANNED |
| E2E-2 | Tier 1 Feature Coverage Tests | ≥50 test cases covering F1-F10 in isolation | E2E-1 | PLANNED |
| E2E-3 | Tier 2 Boundary & Negative Tests | ≥50 boundary, error handling, and corner case tests | E2E-1 | PLANNED |
| E2E-4 | Tier 3 Cross-Feature & Tier 4 Scenarios | ≥10 pairwise interaction tests and ≥5 end-to-end realistic workloads | E2E-2, E2E-3 | PLANNED |
| E2E-5 | Test Suite Publishing | Publish `TEST_READY.md` summarizing coverage and runner commands | E2E-4 | PLANNED |
