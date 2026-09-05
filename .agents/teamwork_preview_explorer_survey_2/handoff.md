# Handoff Report: Explorer 2 (Database Architecture & Transaction Safety)

## 1. Observation

1. **`src/media_sorter/db.py:59-76`**:
   `get_session_factory` instantiates a new `scoped_session` on every call inside `get_db_session`:
   ```python
   def get_session_factory(engine: Engine) -> scoped_session[Session]:
       return scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

   @contextmanager
   def get_db_session(engine: Engine) -> Generator[Session, None, None]:
       session_factory = get_session_factory(engine)
       session: Session = session_factory()
       try:
           yield session
           session.commit()
       except Exception:
           session.rollback()
           raise
       finally:
           session.close()
   ```
   No `session_factory.remove()` is called, and `scoped_session` is recreated on every invocation.

2. **`src/media_sorter/sorter.py:264-306`**:
   Post-run library cataloging references `op.status` on `report.operations`:
   ```python
   with get_db_session(self.engine) as session:
       for op in report.operations:
           if op.status == OperationStatus.COMMITTED.value:
               ...
   ```
   In `src/media_sorter/executor.py:99-111`, `PlannedOperation` contains:
   ```python
   @dataclass
   class PlannedOperation:
       src: Path
       dst: Path
       action: ActionType
       category: str
       confidence: float
       details: Dict[str, Any] = field(default_factory=dict)
       is_conflict: bool = False
       conflict_resolved_dst: Optional[Path] = None
       quarantine: bool = False
       quarantine_reason: Optional[str] = None
   ```
   `PlannedOperation` lacks a `status` attribute. Accessing `op.status` raises `AttributeError: 'PlannedOperation' object has no attribute 'status'`, caught and silenced by `except Exception as e: logger.error(...)` at line 305.

3. **`alembic/versions/a3cc170248be_initial_schema.py:21-100` vs `src/media_sorter/models.py:162-184`**:
   The initial Alembic migration creates `batches`, `config_audit`, `files`, `quarantine`, and `operations`. `LibraryItem` (`__tablename__ = "library_items"`) is defined in `models.py` but is **not** created in the migration script. No other migrations exist in `alembic/versions/`.

4. **`src/media_sorter/server.py:576-608` & `803-820`**:
   The `GET /api/files` endpoint calls `inspect_downloads_folder()`, which performs database mutations on read requests:
   ```python
   with get_db_session(engine) as sess:
       for show_item in shows_list:
           record_detected_item(
               sess,
               settings,
               show_item["show_name"],
               "tv",
               destination_folder=show_item["believed_destination_folder"],
               poster_url=show_item.get("poster_url"),
               delta_count=show_item["count"],
           )
   ```
   In `library.py:185-186`, `item.item_count = max(0, item.item_count + delta_count)` adds `delta_count` cumulatively on every call to `GET /api/files`.

5. **`src/media_sorter/sorter.py:242, 313-324` & `server.py:1114-1172`**:
   `sorter.run()` acquires `acquire_process_lock(lock_path)`, but `sorter.rollback()`, `sorter.rollback_all()`, `manual_sort_file()`, and quarantine resolution/undo endpoints do not acquire any lock before performing file moves and database mutations.

6. **`src/media_sorter/server.py:632-641`**:
   `auto_sort_worker()` invokes synchronous `sorter.run()` directly inside an `async def` function on the FastAPI event loop, blocking HTTP request handling.

7. **`src/media_sorter/executor.py:520-575`**:
   `rollback_batch()` unconditionally sets `batch.status = "ROLLED_BACK"` even if individual operations fail during reversal; furthermore, `FileRecord` for `dst` is never removed or marked reverted.

8. **`src/media_sorter/quarantine.py:72-105`**:
   `undo_item()` resets `rec.status = QuarantineStatus.PENDING.value` and commits to the database even if `shutil.move(dst_path, src_path)` fails with an exception.

---

## 2. Logic Chain

1. **Session Scope & Registry Leaks**:
   - Observation (1) shows `scoped_session(sessionmaker(...))` called inside `get_db_session()`.
   - In SQLAlchemy, `scoped_session` maintains a registry of sessions keyed by thread or context.
   - Instantiating `scoped_session` within a generator function creates a new registry wrapper on every call and closes the session without calling `.remove()`.
   - Therefore, `scoped_session` provides zero registry benefits here while introducing unnecessary object overhead and bypassing standard dependency injection patterns.

2. **Silenced Failure of Library Catalog Updates**:
   - Observation (2) shows that `report.operations` contains `PlannedOperation` instances.
   - Line 271 checks `op.status == OperationStatus.COMMITTED.value`, which fails with `AttributeError`.
   - The broad `except Exception` block at line 304 catches this error and logs it without raising or updating the catalog.
   - Therefore, live execution runs fail to update `LibraryItem` entries in the database, breaking show/movie library catalog synchronization after sorting.

3. **Schema Divergence in Alembic**:
   - Observation (3) verifies that `library_items` is absent from `a3cc170248be_initial_schema.py`.
   - Any deployment running standard database migrations (`alembic upgrade head`) will fail to create the `library_items` table, leading to `sqlite3.OperationalError: no such table: library_items` unless `init_db()` is run beforehand.

4. **Counter Inflation on Read Requests**:
   - Observation (4) shows `GET /api/files` triggers `inspect_downloads_folder()`, which calls `record_detected_item(..., delta_count=show_item["count"])`.
   - `record_detected_item` performs `item.item_count += delta_count` and commits to the database.
   - Therefore, every page refresh or polling call to `/api/files` mutates the database and compounds the reported item count erroneously.

5. **Race Conditions in Concurrent Operations**:
   - Observation (5) reveals that while batch sorting uses `acquire_process_lock`, rollbacks and manual sorts execute without locking.
   - If an automated sort run occurs while a user triggers a rollback or manual sort, both processes concurrently modify the filesystem and write to the database.
   - Therefore, data corruption and `sqlite3.OperationalError: database is locked` can occur under concurrent usage.

---

## 3. Caveats

1. **Non-SQLite Engines**: The application currently targets SQLite exclusively (via SQLite PRAGMAs and WAL mode). PostgreSQL or MySQL support was not investigated as the configuration and codebase currently specify SQLite connection strings (`sqlite:///...`).
2. **`ConfigAudit` Usage**: The `ConfigAudit` model is defined in `models.py` and exists in the schema, but is not currently populated by any service code. Its retention or utilization in R2 should be confirmed by the team.
3. **External Metadata Rate Limits**: TMDB API integration in `classifier.py` was surveyed only in the context of database updates, not external network timeouts or rate-limiting reliability.

---

## 4. Conclusion

The database layer contains a functional core with SQLite WAL mode and basic operation journaling, but suffers from several critical architectural vulnerabilities and bugs that violate Requirement R2 (Database Reliability and Transactional Safety):
- Broken `scoped_session` lifecycle in `db.py`.
- Silent `AttributeError` preventing library catalog updates in `sorter.py`.
- Alembic migration desynchronization omitting `library_items`.
- Read-endpoint side effects inflating counters in `server.py`.
- Missing concurrency locks for rollback and manual operations.
- Event loop blocking by the auto-sort background worker.

A targeted refactoring of `db.py`, `sorter.py`, `server.py`, `executor.py`, and Alembic migrations will resolve all identified reliability risks while preserving 100% API and dashboard backward compatibility.

---

## 5. Verification Method

1. **Verify Existing Passing Test Baseline**:
   Run `.venv/bin/pytest` to confirm that all 75 existing tests currently pass cleanly:
   ```bash
   .venv/bin/pytest
   ```
2. **Verify Missing Migration**:
   Inspect Alembic migration history against `models.py`:
   ```bash
   .venv/bin/python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; script = ScriptDirectory.from_config(Config('alembic.ini')); print([rev.revision for rev in script.walk_revisions()])"
   ```
   Inspect `alembic/versions/a3cc170248be_initial_schema.py` line 21-100 to verify `library_items` is omitted.
3. **Verify `PlannedOperation` Attribute Mismatch**:
   Run in Python:
   ```bash
   .venv/bin/python -c "from media_sorter.executor import PlannedOperation; from pathlib import Path; from media_sorter.config import ActionType; op = PlannedOperation(Path('a'), Path('b'), ActionType.MOVE, 'tv', 0.9); print(hasattr(op, 'status'))"
   ```
   Output is `False`. Accessing `op.status` raises `AttributeError`.
4. **Inspect Database Schema**:
   Verify existing SQLite tables in `media_sorter.db`:
   ```bash
   .venv/bin/python -c "import sqlite3; con = sqlite3.connect('media_sorter.db'); print(con.execute(\"SELECT name FROM sqlite_master WHERE type='table';\").fetchall())"
   ```
   Tables present: `batches`, `files`, `quarantine`, `config_audit`, `operations`, `library_items`.

---

