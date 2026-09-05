# Dispatch for Explorer 2 (Survey: Database Architecture & Transaction Safety)

## Mission
Investigate the database architecture, schema models, session lifecycle, connection pooling, concurrency handling, and transaction safety.

## Input Context
- User request: `/md0/media-sorter/ORIGINAL_REQUEST.md`
- Codebase root: `/md0/media-sorter`
- Working directory: `/md0/media-sorter/.agents/teamwork_preview_explorer_survey_2`

## Specific Investigation Tasks
1. Identify all database-related files (engine, session management, models, queries, repositories, migrations).
2. Examine session management: how sessions/connections are created, shared, closed, and used across concurrent requests. Look for generator/context manager misuse, uncommitted mutations, or leaked connections.
3. Examine transaction boundaries and rollback handling: how errors trigger rollbacks, whether partial writes can corrupt state, and how concurrent operations (e.g. sort runs, rollbacks, quarantine operations) interact with the database.
4. Enumerate all tables, models, and data structures (library, quarantine, history/operations, etc.).
5. Identify areas needing hardening to fulfill R2 (Database Reliability and Transactional Safety).

## Output

## 2026-09-05T18:49:22Z
You are Explorer 2 (Database Architecture & Transaction Safety).
Your working directory is: /md0/media-sorter/.agents/teamwork_preview_explorer_survey_2
Your dispatch instructions are at: /md0/media-sorter/.agents/teamwork_preview_explorer_survey_2/DISPATCH.md
MANDATORY: Read /md0/media-sorter/ORIGINAL_REQUEST.md first before starting work.

Conduct a comprehensive survey of:
1. All database-related files (engine, session management, models, queries, repositories, migrations).
2. Session lifecycle: how sessions/connections are created, scoped, used across concurrent requests; check for generator/context manager misuse, uncommitted mutations, leaked connections.
3. Transaction boundaries and rollback handling: how errors trigger rollbacks, resilience against partial writes and concurrency issues (sort runs, rollbacks, quarantine).
4. All tables, models, and data structures.
5. Hardening recommendations for R2.

Write your findings to /md0/media-sorter/.agents/teamwork_preview_explorer_survey_2/report.md and deliver a self-contained handoff.md in your working directory. Send a completion message back to orchestrator when finished.
