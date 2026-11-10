"""Database engine and sessions for the station database (SQLite, ADR-0037).

This module is the only place that opens database connections.  Every
connection is configured identically:

*   ``journal_mode = WAL``: readers never block the writer, nor it them.
*   ``synchronous = NORMAL``: a power loss can drop the last commits, never
    corrupt the file.
*   ``foreign_keys = ON``: SQLite enforces references only when asked.
*   ``busy_timeout``: a writer waits for the lock instead of failing at once.

Every transaction starts with ``BEGIN IMMEDIATE``.  It takes the write lock
up front, so a transaction that reads and then writes cannot fail half-way
because another service wrote in between.  The price is that only one
transaction runs at a time: keep them short, and never hold one open
across inference, file I/O or a network call.  A transaction that holds
the lock longer than ``SLOW_TRANSACTION_S`` is logged.

The first connection to a new file creates the schema
(:mod:`silvasonic.core.database.schema`).

Engine and session factory are created on first use, not at import time.
For **integration tests**, create an engine for a temporary file with
``create_station_engine(path)`` and inject it with ``override_engine()``;
call ``reset_engine()`` in teardown.
"""

import os
import sqlite3
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
from silvasonic.core.database.schema import ensure_schema
from silvasonic.core.database.types import to_epoch_us
from silvasonic.core.settings import DatabaseSettings
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = structlog.get_logger()

BUSY_TIMEOUT_MS = 5_000
SLOW_TRANSACTION_S = 1.0
_BEGIN_KEY = "silvasonic_transaction_started"

# Raw SQL (``text()``) bypasses the SQLAlchemy column types.  These adapters
# make a parameter bound there land in the same form the ORM stores: a UUID
# as 32 hex digits (``Uuid`` on SQLite), a datetime as epoch microseconds
# (``UTCDateTime``).  Values read back by raw SQL stay in that stored form.
sqlite3.register_adapter(uuid.UUID, lambda value: value.hex)
sqlite3.register_adapter(datetime, to_epoch_us)


def _enable_wal(cursor: Any) -> None:
    """Switch the file to WAL mode, waiting out a concurrent switch.

    WAL mode is stored in the file, so only the first connection to a new
    database changes it.  That change needs an exclusive lock and, unlike
    other statements, does not wait for one: services that open a new
    database at the same moment would fail with "database is locked".
    """
    deadline = time.monotonic() + BUSY_TIMEOUT_MS / 1000
    while True:
        cursor.execute("PRAGMA journal_mode")
        if str(cursor.fetchone()[0]).lower() == "wal":
            return
        try:
            cursor.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or time.monotonic() > deadline:
                raise
            time.sleep(0.05)  # only on a station's very first start


def _configure_connection(dbapi_connection: Any, _connection_record: Any) -> None:
    """Set the pragmas on a new connection and make sure the schema exists."""
    # The driver must not start transactions itself; ``_begin`` does.
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        _enable_wal(cursor)
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA foreign_keys = ON")
    finally:
        cursor.close()
    ensure_schema(dbapi_connection)


def _begin(connection: Connection) -> None:
    """Start every transaction with the write lock."""
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    connection.info[_BEGIN_KEY] = time.monotonic()


def _end(connection: Connection) -> None:
    """Log a transaction that held the write lock too long."""
    started = connection.info.pop(_BEGIN_KEY, None)
    if started is None:
        return
    held_s = time.monotonic() - started
    if held_s > SLOW_TRANSACTION_S:
        logger.warning(
            "database.slow_transaction",
            held_s=round(held_s, 3),
            limit_s=SLOW_TRANSACTION_S,
        )


def create_station_engine(path: Path | str, *, echo: bool = False) -> AsyncEngine:
    """Create an engine for the database file at ``path``.

    The parent directory must exist; the file is created on first connect.
    """
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        echo=echo,
        # sqlite3's own lock timeout, in seconds; matches busy_timeout
        connect_args={"timeout": BUSY_TIMEOUT_MS / 1000},
    )
    sync_engine = engine.sync_engine
    event.listen(sync_engine, "connect", _configure_connection)
    event.listen(sync_engine, "begin", _begin)
    event.listen(sync_engine, "commit", _end)
    event.listen(sync_engine, "rollback", _end)
    return engine


# ---------------------------------------------------------------------------
# Engine override for tests (Audit T-1)
# ---------------------------------------------------------------------------
_engine_override: AsyncEngine | None = None


def override_engine(engine: AsyncEngine) -> None:  # pragma: no cover
    """Inject a pre-configured engine (for integration tests).

    After calling this, all ``get_session()`` / ``get_db()`` calls use the
    provided engine instead of the one ``SILVASONIC_DB_PATH`` names.
    """
    global _engine_override
    _engine_override = engine
    _get_session_factory.cache_clear()


def reset_engine() -> None:  # pragma: no cover
    """Reset to the default engine (re-reads env vars on next call)."""
    global _engine_override
    _engine_override = None
    _get_engine.cache_clear()
    _get_session_factory.cache_clear()


async def dispose_default_engine() -> None:  # pragma: no cover — integration-tested
    """Close the connections of the engine ``SILVASONIC_DB_PATH`` names, if one exists.

    An aiosqlite connection belongs to the event loop that opened it; tests
    call this before their loop closes.  An injected override engine is left
    to whoever injected it.
    """
    if _engine_override is None and _get_engine.cache_info().currsize:
        await _get_engine().dispose()
    _get_engine.cache_clear()
    _get_session_factory.cache_clear()


# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _get_engine() -> AsyncEngine:
    """Create the engine lazily on first use (cached singleton).

    If ``override_engine()`` was called, returns the override instead.
    """
    if _engine_override is not None:  # pragma: no cover — integration-tested
        return _engine_override
    settings = DatabaseSettings()
    return create_station_engine(
        settings.SILVASONIC_DB_PATH,
        echo=os.getenv("SILVASONIC_SQL_ECHO", "False").lower() == "true",
    )


@lru_cache(maxsize=1)
def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create the async session factory lazily on first use (cached singleton)."""
    return async_sessionmaker(  # pragma: no cover — integration-tested
        bind=_get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Public accessor for the cached session factory singleton.

    Used by ``run_all_seeders()`` to create independent per-seeder
    transactions.
    """
    return _get_session_factory()


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Dependency for FastAPI or other services to get a DB session."""
    async with _get_session_factory()() as session:  # pragma: no cover — integration-tested
        yield session


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession]:
    """Context manager for background tasks/scripts."""
    async with _get_session_factory()() as session:  # pragma: no cover — integration-tested
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
