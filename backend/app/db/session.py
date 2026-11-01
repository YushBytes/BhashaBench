"""Engine and session management.

**Why synchronous.** Phase 1 established `postgresql+psycopg` as the URL
scheme, Alembic runs synchronously, and nothing in the application yet
performs concurrent I/O that an async engine would help with. FastAPI runs a
plain `def` route handler in a worker thread, so a synchronous session does
not block the event loop. Adopting `async_sessionmaker` here would add a
second concurrency model, a greenlet dependency and async-aware migrations for
no present benefit. The repository layer is deliberately thin enough that
moving to an async engine later is a mechanical change.

The engine is created lazily and cached so that importing this module does not
open sockets - which matters for unit tests that never touch a database.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger("bhashabench.db")


@lru_cache
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine.

    `pool_pre_ping` costs one cheap round-trip per checkout and avoids handing
    out a connection the database has already closed - the common failure when
    a developer restarts the Postgres container while the API keeps running.
    """
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        # `echo` stays off in every environment: SQLAlchemy's echo output
        # includes bound parameters, which is a route for data to reach logs.
        echo=False,
        future=True,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory."""
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        # Attributes stay loaded after commit, so a response model can read a
        # just-committed object without triggering another SELECT (or failing
        # once the session is closed).
        expire_on_commit=False,
    )


def reset_engine() -> None:
    """Dispose the cached engine and factory.

    Used by tests that need the engine rebuilt against different settings.
    """
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session for non-HTTP callers (scripts, tests).

    Commits on success, rolls back on any exception, and always closes.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session.

    The session is rolled back and closed in `finally`, so a connection is
    returned to the pool even when a handler raises. Committing is left to the
    service layer: a read-only request should not commit, and a handler that
    raises midway must not have part of its work persisted.

    The explicit `rollback()` before close matters - closing a session with an
    open transaction returns the connection to the pool still inside that
    transaction, which can leave locks held.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def check_database_connection() -> tuple[bool, str]:
    """Probe the database with `SELECT 1`.

    Returns `(reachable, detail)`. The detail never includes the connection
    URL or the driver's message verbatim, because both can carry credentials;
    only the exception class name is reported.
    """
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Database connection probe failed: %s", type(exc).__name__)
        return False, f"Connection failed ({type(exc).__name__})."
    return True, "Connected; SELECT 1 succeeded."


__all__ = [
    "check_database_connection",
    "get_db",
    "get_engine",
    "get_session_factory",
    "reset_engine",
    "session_scope",
]
