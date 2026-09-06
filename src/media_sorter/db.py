"""Database initialization and session management for Media Sorter.

Configures SQLite with Write-Ahead Logging (WAL) mode and foreign keys enabled
for transactional safety, high concurrency, and crash resilience.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, scoped_session, sessionmaker

from .models import Base

DEFAULT_DB_PATH = Path("media_sorter.db")


def get_engine(db_path: Path | str = DEFAULT_DB_PATH, wal_mode: bool = True) -> Engine:
    """Create and configure a SQLite SQLAlchemy engine.

    Enables WAL mode and enforces foreign keys for transactional integrity.
    """
    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{path}"

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
            cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


def init_db(engine: Optional[Engine] = None, db_path: Path | str = DEFAULT_DB_PATH) -> Engine:
    """Initialize all tables defined in models.py if they do not exist."""
    if engine is None:
        engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine


_ENGINE_SESSION_FACTORIES: dict[Engine, scoped_session[Session]] = {}


def get_session_factory(engine: Engine) -> scoped_session[Session]:
    """Retrieve or create a cached scoped session factory bound to the given engine."""
    if engine not in _ENGINE_SESSION_FACTORIES:
        _ENGINE_SESSION_FACTORIES[engine] = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=engine)
        )
    return _ENGINE_SESSION_FACTORIES[engine]


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
        session_factory.remove()
