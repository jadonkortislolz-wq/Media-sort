# Comprehensive Database Architecture & Transaction Safety Survey Report

**Explorer 2 (Database Architecture & Transaction Safety)**  
**Date**: 2026-09-05  
**Codebase**: `/md0/media-sorter`  
**Target Milestone**: R2 (Database Reliability and Transactional Safety) & Architectural Hardening  

---

## Executive Summary

A comprehensive, end-to-end investigation of the Media Sorter database layer was conducted, spanning schema design, session lifecycle, connection pooling, transactional boundaries, rollback integrity, concurrent multi-worker operations, and Alembic migrations.

### Key Highlights & Critical Findings:
1. **Broken `scoped_session` Anti-Pattern (`src/media_sorter/db.py:59-76`)**: `scoped_session` is re-instantiated inside `get_db_session()` on every invocation, defeating thread-local caching, leaking registry instances, and performing no `.remove()` cleanup.
2. **Silent Post-Run Failure via `AttributeError` (`src/media_sorter/sorter.py:271`)**: In `MediaSorterApp.run()`, post-run library cataloging references `op.status` on `PlannedOperation` objects which do not have a `status` attribute. This causes an unhandled `AttributeError` that is silently swallowed by an overly broad `except Exception: pass`, preventing the library catalog from ever updating after live sort operations.
3. **Severe Schema Desynchronization in Alembic (`alembic/versions/a3cc170248be_initial_schema.py`)**: The `library_items` table is defined in `models.py:162-184` and exists in runtime SQLite databases, but is **entirely absent** from Alembic migrations. Running `alembic upgrade head` on a fresh database fails to produce the `library_items` table.
4. **Side-Effecting Read Queries (`src/media_sorter/server.py:577-608`)**: The `GET /api/files` endpoint calls `inspect_downloads_folder()`, which issues writes to `library_items` via `record_detected_item(..., delta_count=count)`. Every browser refresh or API poll cumulatively increments `item_count`, causing arithmetic counter inflation on read requests.
5. **Missing Process Locks on Rollbacks & Manual Sorting (`src/media_sorter/sorter.py:313-324`, `server.py:1114-1172`)**: While `sorter.run()` acquires an OS file lock (`acquire_process_lock`), `sorter.rollback()`, `sorter.rollback_all()`, manual sorts, and quarantine resolutions do **not** acquire any lock, creating high-risk race conditions and partial filesystem/database states if triggered during active sorting.
6. **Transaction Fragmentation & Disk Thrashing (`src/media_sorter/executor.py:225-375`)**: During batch execution, 2 to 3 separate SQLite write transactions with `commit()` are executed for *every individual file*. For batches with hundreds of files, this causes severe I/O bottlenecking and prevents true atomic rollback if a batch aborts midway.
7. **Event Loop Starvation in Background Auto-Sort (`src/media_sorter/server.py:632-641`)**: The background auto-sort worker executes synchronous blocking pipeline calls directly inside FastAPI's async event loop without delegating to `run_in_executor`.

---

## 1. Inventory of Database-Related Files

| File Path | Role / Purpose | Key Responsibilities |
| :--- | :--- | :--- |
| `src/media_sorter/db.py` | Engine & Session Management | Creates SQLite engine with WAL mode and PRAGMAs; defines `init_db`, `get_session_factory`, and `get_db_session`. |
| `src/media_sorter/models.py` | Declarative ORM Models | Defines `Base`, `OperationStatus`, `QuarantineStatus`, and ORM models: `BatchRecord`, `FileRecord`, `Operation`, `QuarantineRecord`, `ConfigAudit`, `LibraryItem`. |
| `alembic.ini` | Migration Configuration | Configures Alembic migration environment and logging. |
| `alembic/env.py` | Migration Runner | Binds SQLAlchemy engine and `target_metadata = Base.metadata` for migrations. |
| `alembic/versions/a3cc170248be_initial_schema.py` | Initial Schema Migration | Initial migration defining `batches`, `files`, `quarantine`, `config_audit`, and `operations`. **Missing `library_items`.** |
| `src/media_sorter/executor.py` | Execution Engine & Operations Journal | Contains `MediaExecutor` and `acquire_process_lock`. Writes `BatchRecord`, `Operation`, and `FileRecord`; handles rollbacks and crash recovery. |
| `src/media_sorter/library.py` | Library Cataloging Engine | Contains `sync_library_from_disk`, `record_detected_item`, `get_known_shows`, `match_known_show`, and `list_library_items`. Writes directly to `LibraryItem`. |
| `src/media_sorter/quarantine.py` | Quarantine Management | Contains `QuarantineManager` for CRUD operations on `QuarantineRecord` (listing, resolving, ignoring, undoing). |
| `src/media_sorter/sorter.py` | High-Level Orchestrator | Instantiates `MediaSorterApp`; manages pipeline lifecycle, database checks for skip cache, batch execution, and library updates. |
| `src/media_sorter/server.py` | Web Dashboard & REST API | Defines FastAPI endpoints using `get_db_session` across status, batches, rollback, quarantine, library, and manual sort routes; runs background workers. |
| `src/media_sorter/cli.py` | CLI Application | Defines Typer commands (`scan`, `organize`, `rollback`, `history`, `quarantine`) that initialize engine and sessions. |
| `tests/unit/test_config_and_db.py` | Unit Tests | Tests basic engine initialization and batch query. |
| `tests/unit/test_executor_and_rollback.py` | Unit Tests | Tests dry-run, atomic move, collision policies, rollback, and locking. |
| `tests/unit/test_library_and_groups.py` | Unit Tests | Tests library disk synchronization, known shows matching, and library endpoints. |
| `tests/unit/test_quarantine.py` | Unit Tests | Tests quarantine CRUD and undo behavior. |
| `tests/unit/test_server_and_env.py` | Integration / Unit Tests | Tests FastAPI endpoints interacting with database. |
| `tests/integration/test_end_to_end.py` | End-to-End Tests | Full end-to-end integration test verifying sorting, rollback, and quarantine DB state. |

---

## 2. Session Lifecycle & Connection Management Analysis

### 2.1 The `get_session_factory` and `scoped_session` Anti-Pattern

In `src/media_sorter/db.py`:
```python
def get_session_factory(engine: Engine) -> scoped_session[Session]:
    """Create a scoped session factory bound to the given engine."""
    return scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

@contextmanager
def get_db_session(engine: Engine) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
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

#### Architectural Issues:
1. **Ephemeral Registry Overhead**: `scoped_session` is designed as an application-level singleton holding a thread-local registry (`threading.local`). Creating a new `scoped_session` instance *inside* a short-lived function call creates a new registry wrapper on every session request, discarding it immediately upon return.
2. **Missing Registry Teardown**: Calling `session.close()` on a session obtained from `scoped_session` closes the underlying DB connection, but does **not** invoke `session_factory.remove()`.
3. **No Singleton Sessionmaker**: There is no global or application-scoped `sessionmaker` factory. Engine-bound factories are recreated on every call.
4. **Lack of `expire_on_commit=False`**: Default SQLAlchemy session behavior expires object attributes on `commit()`. When `MediaExecutor` or `library` methods commit transactions, accessing model attributes afterwards triggers lazy-loading queries, which fail or re-query if the session is closed or detached.

### 2.2 FastAPI Session Management & Dependency Injection

In `src/media_sorter/server.py`:
- FastAPI provides an idiomatic Dependency Injection mechanism (`Depends(get_db)`). Currently, **no dependency injection is used**.
- Instead, over 17 distinct API route handlers and helper functions manually invoke:
  ```python
  with get_db_session(engine) as session:
      ...
  ```
- This manual scoping causes code duplication, impedes testing/mocking, and leads to inconsistent error responses when database exceptions occur.

### 2.3 SQLite Concurrency & Connection Pooling

In `src/media_sorter/db.py:23-48`:
```python
engine = create_engine(
    db_url,
    connect_args={"check_same_thread": False, "timeout": 30.0},
    pool_pre_ping=True,
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    if wal_mode:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=10000")
    cursor.close()
```

#### Observations:
- **Connection Pool**: By default on SQLite with `check_same_thread=False`, SQLAlchemy uses a `QueuePool` with `pool_size=5` and `max_overflow=10`.
- **WAL Mode**: WAL (Write-Ahead Logging) is enabled, allowing concurrent readers and one writer.
- **`PRAGMA busy_timeout`**: Set to 10,000 ms (10 seconds), which helps mitigate transient locks. However, `busy_timeout` is only set if `wal_mode=True`.
- **Transaction Locking**: SQLAlchemy initiates transactions with deferred `BEGIN`. Under concurrent requests, two connections can start reading and then both attempt to write, leading to `sqlite3.OperationalError: database is locked`. SQLite write transactions should start with `BEGIN IMMEDIATE` to prevent deadlocks.

### 2.4 Event Loop Blocking in Background Workers

In `src/media_sorter/server.py:632-641`:
```python
async def auto_sort_worker():
    while True:
        interval = settings.general.scan_interval_seconds
        if interval > 0:
            try:
                sorter = MediaSorterApp(settings, engine)
                sorter.run()
            except Exception as e:
                logger.error("Auto-sort background task error", error=str(e))
        await asyncio.sleep(max(interval, 10) if interval > 0 else 10)
```
- `sorter.run()` is a synchronous, CPU- and I/O-intensive operation that scans directories, computes file hashes, and executes synchronous database queries.
- Running `sorter.run()` directly inside `auto_sort_worker` **blocks the asyncio event loop entirely**, causing HTTP requests to hang until the scan and sort cycle finishes.
- In contrast, `initial_library_sync` (lines 644-652) correctly uses `asyncio.get_running_loop().run_in_executor(None, initial_library_sync)`.

---

## 3. Transaction Boundaries, Rollback Handling & Concurrency Safety

### 3.1 Silent Failure: `AttributeError` in `MediaSorterApp.run()`

In `src/media_sorter/sorter.py:264-306`:
```python
if not is_dry_run and report.moved_files > 0:
    try:
        from .library import record_detected_item
        shows_dir = self.settings.get_destination_path("tv")
        movies_dir = self.settings.get_destination_path("movie")
        with get_db_session(self.engine) as session:
            for op in report.operations:
                if op.status == OperationStatus.COMMITTED.value:  # <-- BUG HERE
                    ...
    except Exception as e:
        logger.error("Error updating library from execution report", error=str(e))
```

#### Evidence:
- `report.operations` is populated from `validated_plan`, which contains instances of `PlannedOperation` (defined in `src/media_sorter/executor.py:99-111`).
- `PlannedOperation` has fields: `src`, `dst`, `action`, `category`, `confidence`, `details`, `is_conflict`, `conflict_resolved_dst`, `quarantine`, `quarantine_reason`. **It does NOT have a `status` field.**
- `op.status` unconditionally raises `AttributeError: 'PlannedOperation' object has no attribute 'status'`.
- The exception is trapped by `except Exception as e`, logging an error message and silently aborting the library catalog update.
- **Impact**: No live sort batch ever records moved files into `LibraryItem`.

### 3.2 Transaction Fragmentation & Lack of Batch Atomicity

In `src/media_sorter/executor.py`:
1. `execute_batch` begins by creating a `BatchRecord(status="IN_PROGRESS")` and calling `self.session.commit()`.
2. For every file:
   - Live execution calls `_execute_single_op`:
     - Creates `Operation(status=IN_PROGRESS)` -> `self.session.commit()`
     - Performs filesystem move (`_safe_move`)
     - Updates `Operation(status=COMMITTED)` and `FileRecord` -> `self.session.commit()`
     - On exception: updates `Operation(status=FAILED)` -> `self.session.commit()` -> `raise`
3. If an unhandled exception or crash occurs halfway through a batch of 50 files:
   - 25 files are already committed to the database as `COMMITTED`.
   - The outer `with get_db_session(self.engine) as session:` receives the exception and calls `session.rollback()`.
   - `session.rollback()` only discards uncommitted mutations in the active transaction; the prior 25 committed operations remain in the database.
   - The batch is left in `status="IN_PROGRESS"`.
   - While `recover_interrupted_batches()` (lines 590-609) marks `Operation` records in `IN_PROGRESS` as `FAILED`, it **fails to update `BatchRecord.status`** to `FAILED` or `PARTIAL_FAILURE`.

### 3.3 Rollback Handling Inconsistencies

In `src/media_sorter/executor.py:519-575`:
1. **Unconditional Success Flagging**:
   - `rollback_batch()` iterates through all committed operations in reverse order:
     ```python
     for op in ops:
         try:
             # move dst back to src...
             op.status = OperationStatus.ROLLED_BACK.value
         except Exception as e:
             logger.error("Error reverting operation during rollback", op_id=op.id, error=str(e))
     
     batch.status = "ROLLED_BACK"
     self.session.commit()
     ```
   - If an I/O error or permission error prevents half of the files from reverting, `op.status` remains `COMMITTED`, but `batch.status` is unconditionally set to `"ROLLED_BACK"`.
   - Subsequent rollback attempts (`rollback()` or `rollback_all()`) query `filter(BatchRecord.status != "ROLLED_BACK")`, permanently stranding the failed operations.
2. **Orphaned `FileRecord` on Rollback**:
   - When files are organized, `FileRecord` is recorded for `dst` with `status="organized"`.
   - When `rollback_batch` reverts the file from `dst` back to `src`, `FileRecord` for `dst` is **not deleted or updated**. The database continues to assert that `dst` is an active organized file.
3. **Orphaned `LibraryItem` on Rollback**:
   - `LibraryItem.item_count` is not decremented when a batch is rolled back.

### 3.4 Quarantine Undo Edge-Case Failure

In `src/media_sorter/quarantine.py:72-105`:
```python
if rec.status == QuarantineStatus.RESOLVED.value and rec.resolved_path:
    dst_path = Path(rec.resolved_path)
    src_path = Path(rec.src)
    if dst_path.exists():
        src_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(dst_path, src_path)
        except Exception as e:
            logger.error("Failed restoring quarantine file to src", ...)
    rec.status = QuarantineStatus.PENDING.value
    rec.resolved_path = None
    rec.resolved_at = None
    self.session.commit()
    return True
```
- If `dst_path.exists()` is `False` (file was removed or renamed outside the application) or `shutil.move` fails, `undo_item` still commits the status change to `PENDING` with `resolved_path = None` and returns `True`.
- The database state becomes desynchronized from the actual filesystem.

### 3.5 Missing Concurrency Locks across Write Endpoints

1. `sorter.run()` uses:
   ```python
   lock_path = self.settings.get_database_path().with_suffix(".lock")
   with acquire_process_lock(lock_path):
       ...
   ```
2. However, the following write-heavy operations execute **without** acquiring `acquire_process_lock`:
   - `sorter.rollback()` / `sorter.rollback_all()` (`src/media_sorter/sorter.py:313-324`)
   - `manual_sort_file()` (`src/media_sorter/server.py:1114-1172`)
   - `resolve_quarantine()` / `bulk_resolve_quarantine()` (`src/media_sorter/server.py:1024-1085`)
   - `undo_quarantine()` / `bulk_undo_quarantine()` (`src/media_sorter/server.py:1087-1112`)
   - `sort_group_endpoint()` movie branch (`src/media_sorter/server.py:1308-1345`)
3. If an automated sort run or CLI run executes concurrently with a user resolving quarantine or performing a rollback via the web dashboard, file collisions and database lock errors will occur.

---

## 4. Comprehensive Schema, Models & Data Structure Enumeration

The application uses SQLAlchemy Declarative ORM with SQLite backend (`media_sorter.db`).

```
                    ┌─────────────────────────┐
                    │      batches            │
                    ├─────────────────────────┤
                    │ id (PK, UUID)           │◄───────┐
                    │ created_at              │        │
                    │ completed_at            │        │
                    │ dry_run                 │        │
                    │ status                  │        │ 1:N
                    │ total_files             │        │
                    │ moved_files             │        │
                    │ skipped_files           │        │
                    │ failed_files            │        │
                    │ quarantined_files       │        │
                    └─────────────────────────┘        │
                                                       │
                    ┌─────────────────────────┐        │
                    │      operations         │        │
                    ├─────────────────────────┤        │
                    │ id (PK, autoincrement)  │        │
                    │ batch_id (FK) ──────────┼────────┘
                    │ src                     │
                    │ dst                     │
                    │ action                  │
                    │ status                  │
                    │ category                │
                    │ confidence              │
                    │ src_hash / dst_hash     │
                    │ backup_path             │
                    │ details (JSON)          │
                    │ error_message           │
                    │ created_at              │
                    │ completed_at            │
                    └─────────────────────────┘

┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│       files             │  │      quarantine         │  │     library_items       │
├─────────────────────────┤  ├─────────────────────────┤  ├─────────────────────────┤
│ id (PK, autoincrement)  │  │ id (PK, autoincrement)  │  │ id (PK, autoincrement)  │
│ path (UNIQUE)           │  │ src (UNIQUE)            │  │ title                   │
│ size                    │  │ suggested_category      │  │ category (tv/movie)     │
│ mtime                   │  │ confidence              │  │ year                    │
│ content_hash            │  │ reason                  │  │ destination_folder      │
│ status                  │  │ signals (JSON)          │  │ poster_url              │
│ category                │  │ status (PENDING/...)    │  │ item_count              │
│ confidence              │  │ resolved_path           │  │ seasons_count           │
│ first_seen              │  │ created_at              │  │ first_detected          │
│ last_processed          │  │ resolved_at             │  │ last_updated            │
└─────────────────────────┘  └─────────────────────────┘  │ extra_info (JSON)       │
                                                           ├─────────────────────────┤
┌─────────────────────────┐                                │ UQ(title, category)     │
│     config_audit        │                                └─────────────────────────┘
├─────────────────────────┤
│ id (PK, autoincrement)  │
│ loaded_at               │
│ config_json (JSON)      │
└─────────────────────────┘
```

### 4.1 Detailed Table Definitions

#### 1. Table `batches` (`BatchRecord`)
- **Primary Key**: `id` (`String(36)`)
- **Columns**:
  - `created_at`: `DateTime(timezone=True)`, non-nullable, default `utc_now`
  - `completed_at`: `DateTime(timezone=True)`, nullable
  - `dry_run`: `Boolean`, non-nullable, default `False`
  - `status`: `String(32)`, non-nullable, default `"IN_PROGRESS"` (valid: `IN_PROGRESS`, `COMPLETED`, `PARTIAL_FAILURE`, `ROLLED_BACK`)
  - `total_files`: `Integer`, default 0
  - `moved_files`: `Integer`, default 0
  - `skipped_files`: `Integer`, default 0
  - `failed_files`: `Integer`, default 0
  - `quarantined_files`: `Integer`, default 0
- **Relationships**: `operations` -> `relationship("Operation", back_populates="batch", cascade="all, delete-orphan")`
- **Indexes**: `ix_batches_created_at` on `(created_at)`

#### 2. Table `files` (`FileRecord`)
- **Primary Key**: `id` (`Integer`, autoincrement)
- **Columns**:
  - `path`: `String(1024)`, unique, non-nullable
  - `size`: `Integer`, non-nullable (Recommendation: change to `BigInteger` for 4GB+ files)
  - `mtime`: `Float`, non-nullable
  - `content_hash`: `String(64)`, nullable (partial SHA-256)
  - `status`: `String(32)`, non-nullable, default `"scanned"` (`scanned`, `organized`, `quarantined`, `skipped`, `error`)
  - `category`: `String(32)`, nullable
  - `confidence`: `Float`, nullable
  - `first_seen`: `DateTime(timezone=True)`, non-nullable, default `utc_now`
  - `last_processed`: `DateTime(timezone=True)`, nullable
- **Indexes**: `ix_files_path` on `(path)`, `ix_files_status` on `(status)`

#### 3. Table `operations` (`Operation`)
- **Primary Key**: `id` (`Integer`, autoincrement)
- **Foreign Keys**: `batch_id` -> `batches.id`
- **Columns**:
  - `src`: `String(1024)`, non-nullable
  - `dst`: `String(1024)`, non-nullable
  - `action`: `String(32)`, non-nullable (`move`, `copy`, `link`, `hardlink`)
  - `status`: `String(32)`, non-nullable, default `"PLANNED"` (values from `OperationStatus`)
  - `category`: `String(32)`, nullable
  - `confidence`: `Float`, nullable
  - `src_hash`: `String(64)`, nullable
  - `dst_hash`: `String(64)`, nullable
  - `backup_path`: `String(1024)`, nullable
  - `details`: `JSON`, nullable
  - `error_message`: `Text`, nullable
  - `created_at`: `DateTime(timezone=True)`, non-nullable, default `utc_now`
  - `completed_at`: `DateTime(timezone=True)`, nullable
- **Indexes**: `ix_operations_batch_id`, `ix_operations_status`, `ix_operations_src`, `ix_operations_dst`

#### 4. Table `quarantine` (`QuarantineRecord`)
- **Primary Key**: `id` (`Integer`, autoincrement)
- **Columns**:
  - `src`: `String(1024)`, unique, non-nullable
  - `suggested_category`: `String(32)`, nullable
  - `confidence`: `Float`, nullable
  - `reason`: `String(256)`, non-nullable
  - `signals`: `JSON`, nullable
  - `status`: `String(32)`, non-nullable, default `"PENDING"` (`PENDING`, `RESOLVED`, `IGNORED`)
  - `resolved_path`: `String(1024)`, nullable
  - `created_at`: `DateTime(timezone=True)`, non-nullable, default `utc_now`
  - `resolved_at`: `DateTime(timezone=True)`, nullable
- **Indexes**: `ix_quarantine_src` on `(src)`, `ix_quarantine_status` on `(status)`

#### 5. Table `config_audit` (`ConfigAudit`)
- **Primary Key**: `id` (`Integer`, autoincrement)
- **Columns**:
  - `loaded_at`: `DateTime(timezone=True)`, non-nullable, default `utc_now`
  - `config_json`: `JSON`, non-nullable
- **Indexes**: `ix_config_loaded` on `(loaded_at)`
- *Note*: Model exists but is currently unreferenced by write paths in the codebase.

#### 6. Table `library_items` (`LibraryItem`)
- **Primary Key**: `id` (`Integer`, autoincrement)
- **Columns**:
  - `title`: `String(256)`, non-nullable
  - `category`: `String(32)`, non-nullable (`tv` or `movie`)
  - `year`: `Integer`, nullable
  - `destination_folder`: `String(1024)`, non-nullable
  - `poster_url`: `String(1024)`, nullable
  - `item_count`: `Integer`, non-nullable, default 0
  - `seasons_count`: `Integer`, non-nullable, default 0
  - `first_detected`: `DateTime(timezone=True)`, non-nullable, default `utc_now`
  - `last_updated`: `DateTime(timezone=True)`, non-nullable, default `utc_now`
  - `extra_info`: `JSON`, nullable
- **Constraints**: `UniqueConstraint("title", "category", name="uq_library_title_category")`
- **Indexes**: `ix_library_category` on `(category)`, `ix_library_title` on `(title)`
- **Migration Status**: **MISSING from Alembic migration history.**

---

## 5. Hardening Recommendations for R2 (Database Reliability and Transactional Safety)

Based on direct code examination and architectural analysis, the following concrete recommendations are formulated for the implementation phase:

### 5.1 Redesign Session Factory and Lifecycle (`db.py`)
1. **Remove Ephemeral `scoped_session` Instantiation**:
   - Define a single engine-bound `sessionmaker`:
     ```python
     def get_session_maker(engine: Engine) -> sessionmaker[Session]:
         return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
     ```
2. **Idiomatic Context Manager**:
   - Update `get_db_session` to accept `Engine | sessionmaker`:
     ```python
     @contextmanager
     def get_db_session(bind: Engine | sessionmaker) -> Generator[Session, None, None]:
         factory = bind if isinstance(bind, sessionmaker) else get_session_maker(bind)
         session = factory()
         try:
             yield session
             session.commit()
         except Exception:
             session.rollback()
             raise
         finally:
             session.close()
     ```
3. **FastAPI Dependency Injection**:
   - Provide `get_db` for FastAPI route dependencies:
     ```python
     def get_db(request: Request) -> Generator[Session, None, None]:
         engine = request.app.state.engine
         with get_db_session(engine) as session:
             yield session
     ```

### 5.2 Fix Silent Post-Run Failure (`sorter.py:271`)
- Fix the attribute mismatch in `MediaSorterApp.run()`:
  - Option A: Add `status: OperationStatus = OperationStatus.PLANNED` to `PlannedOperation` dataclass in `executor.py`, updated to `OperationStatus.COMMITTED` upon successful execution.
  - Option B: Query committed `Operation` records directly from the database for `report.batch_id` before updating the library catalog.
  - Remove blanket `except Exception: pass` and log informative diagnostics with specific error types.

### 5.3 Eliminate Read-Time Database Mutation in `/api/files` (`server.py:577-608`)
- Remove the call to `record_detected_item(sess, settings, ...)` from `inspect_downloads_folder()`.
- A `GET /api/files` request should be strictly read-only.
- Library items should only be recorded when files are actually moved/organized, or via the explicit `POST /api/library/rescan` endpoint.
- Correct the `item_count` calculation so it is based on actual detected file counts on disk rather than cumulative additive deltas.

### 5.4 Synchronize Alembic Migrations
- Generate a new Alembic migration:
  `alembic revision --autogenerate -m "add_library_items_table"`
- Ensure `library_items` table, its unique constraint `uq_library_title_category`, and its indexes are fully captured.
- Verify `alembic upgrade head` cleanly provisions all 6 tables from scratch.

### 5.5 Expand Process Lock to Cover Rollback and Manual Operations
- Extend `acquire_process_lock` to wrap:
  - `sorter.rollback()` and `sorter.rollback_all()`
  - Manual sort endpoints (`/api/files/manual-sort`, `/api/files/sort-group`)
  - Quarantine resolution and undo endpoints
- This prevents concurrent execution conflicts between background auto-sorting and interactive user operations.

### 5.6 Optimize Batch Execution Transactions
- In `MediaExecutor.execute_batch()`:
  - Avoid opening and committing a new SQLite write transaction for every single file.
  - Maintain an in-memory operations log or flush state in small batches (e.g. chunks of 50-100 files) or use SQLite savepoints.
  - If a batch has partial failures, update `BatchRecord.status = "PARTIAL_FAILURE"` and record failed operation error messages cleanly.

### 5.7 Ensure Non-Blocking Background Tasks in FastAPI
- In `server.py:auto_sort_worker`, delegate `sorter.run()` to `asyncio.get_running_loop().run_in_executor(None, sorter.run)`.
- This ensures the FastAPI event loop remains responsive to user requests during intensive sorting operations.

### 5.8 Robustness in Rollback & Quarantine Undo
- In `rollback_batch()`: If any operation fails to revert, set `batch.status = "PARTIAL_ROLLBACK"` rather than `"ROLLED_BACK"`.
- Clean up `FileRecord` on rollback so reverted destination files are marked as removed or status updated to `"rolled_back"`.
- In `QuarantineManager.undo_item()`: Verify `shutil.move` actually succeeded before committing the database record status change to `PENDING`.

---

