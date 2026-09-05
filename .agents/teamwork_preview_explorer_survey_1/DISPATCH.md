# Dispatch for Explorer 1 (Survey: Architecture & Server & Test Suite Baseline)

## Mission
Investigate the current codebase architecture, monolithic server structure, REST API routing, template rendering, and existing test suite baseline.

## Input Context
- User request: `/md0/media-sorter/ORIGINAL_REQUEST.md`
- Codebase root: `/md0/media-sorter`
- Working directory: `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_1`

## Specific Investigation Tasks
1. Map full directory and file layout of `/md0/media-sorter`.
2. Inspect the server entry points and monolithic modules (e.g., server orchestration, routes, templates).
3. Enumerate all existing REST API endpoints (`/api/status`, `/api/files`, `/api/run`, `/api/rollback`, `/api/library`, `/api/quarantine`, etc.) and their request/response schemas.
4. Inspect the single-page web dashboard and template rendering: Folder Explorer (`.txt`/`.srt` exclusions), Library catalog views, quarantine queue, theme dropdown & swatches, and classification modals.
5. Inspect `tests/` directory: existing 75 tests, fixtures, test runner configuration, coverage setup, and current test status.
6. Enumerate all required features, modules, and dependencies for R1 (Architectural Decoupling) and backward compatibility.

## Output
Write your comprehensive survey report to `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_1/report.md` and handoff summary to `handoff.md`.

## 2026-09-05T18:49:22Z
You are Explorer 1 (Codebase Architecture & Server Monolith & Test Baseline).
Your working directory is: /md0/media-sorter/.agents/teamwork_preview_explorer_survey_1
Your dispatch instructions are at: /md0/media-sorter/.agents/teamwork_preview_explorer_survey_1/DISPATCH.md
MANDATORY: Read /md0/media-sorter/ORIGINAL_REQUEST.md first before starting work.

Conduct a comprehensive survey of:
1. Full directory and file layout of /md0/media-sorter.
2. Server entry points and monolithic modules (server orchestration, UI template rendering, endpoint handling).
3. All existing REST API endpoints (/api/status, /api/files, /api/run, /api/rollback, /api/library, /api/quarantine, etc.) and their request/response schemas.
4. Single-page web dashboard: template rendering, Folder Explorer (.txt/.srt exclusions), Library catalog views, quarantine queue, theme dropdown & swatches, classification modals.
5. Existing test suite in tests/: 75 baseline tests, test runner configuration, coverage setup, current pass/fail status.

Write your findings to /md0/media-sorter/.agents/teamwork_preview_explorer_survey_1/report.md and deliver a self-contained handoff.md in your working directory. Send a completion message back to orchestrator when finished.
