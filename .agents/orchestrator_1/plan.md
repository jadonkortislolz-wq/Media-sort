# Project Plan: Media Sorter Hardening & Test Expansion

## Objective
Conduct a comprehensive codebase audit, architectural decoupling, database transaction hardening, and test suite expansion for the Media Sorter application to ensure production-grade reliability, modularity, and >=90% test coverage with zero regressions.

## Methodology & Pattern
Project Orchestration Pattern with Dual Track (Implementation & E2E Testing).
- Survey phase with 3 parallel Explorers to build comprehensive Feature Inventory and architecture map.
- Top-level orchestrator decomposes into modular milestones and delegates to sub-orchestrators.
- E2E Testing Track designs opaque-box requirement-driven test suite (Tiers 1-4).
- Implementation Track implements decoupled modules, database hardening, and safety guardrails.
- Final Milestone executes Tier 1-4 validation followed by Tier 5 adversarial coverage hardening.
- Forensic Auditor gate checks on all milestones with zero tolerance for integrity violations.

## Phases
1. **Phase 0: Survey & Scope Mapping**
   - Explorer 1: Monolithic server decomposition & routing & template rendering audit.
   - Explorer 2: Database session lifecycle, connection pooling, and concurrency audit.
   - Explorer 3: Sorting pipeline, tokenization, companion files, and filesystem safety audit.
   - Synthesis -> Build `PROJECT.md` and feature inventory.

2. **Phase 1: Dual Track Dispatch**
   - **Track A (E2E Testing Track)**: Delegate to E2E Testing Orchestrator. Build test infrastructure and Tiers 1-4 test suite per `TEST_INFRA.md`, publish `TEST_READY.md`.
   - **Track B (Implementation Track)**:
     - Milestone 1: Server & Template Architecture Decoupling.
     - Milestone 2: Database Reliability & Transactional Safety.
     - Milestone 3: Error Handling, Input Validation & Filesystem Safety Guardrails.

3. **Phase 2: Integration & Final Milestone**
   - Sub-orchestrator for Final Milestone:
     - Sub-phase 1: Pass 100% E2E Test Suite (Tiers 1-4).
     - Sub-phase 2: Adversarial Coverage Hardening (Tier 5 white-box challenger loop) to guarantee >=90% coverage on core modules.
   - Final audit and acceptance verification.

## Acceptance Criteria Checklist
- [ ] 100% pass rate on `pytest tests/` (75 existing + all new tests) with zero regressions
- [ ] Core sorting, tokenization, database, and API routing modules achieve or exceed 90% test coverage
- [ ] All new and modified tests use isolated mock directories or temporary fixtures without touching real user media paths (`/md0/jdownloads`, `/md0/movies1`, `/md0/tv1`)
- [ ] Static syntax, import integrity, and code quality checks pass cleanly
- [ ] All existing REST API endpoints remain 100% backward-compatible
- [ ] Single-page web dashboard remains fully functional
- [ ] Companion file behaviors function without regressions
