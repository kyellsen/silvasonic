"""Database session management with lazy initialization.

Engine and session factory are created on first use via ``@lru_cache``,
not at import time.  This eliminates import side-effects, improves
testability, and follows the Zen of Python: *Explicit is better than
implicit.*

For **integration tests**, use ``override_engine(engine)`` to inject
a test-managed engine (e.g. from testcontainers).  Call ``reset_engine()``
in teardown to restore default behaviour.

Example (conftest.py)::

    @pytest.fixture(scope="session")
    def db_engine(postgres_container):
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        override_engine(engine)
        yield engine
        reset_engine()
"""

import os
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from silvasonic.core.settings import DatabaseSettings
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Engine override for tests (Audit T-1)
# ---------------------------------------------------------------------------
_engine_override: AsyncEngine | None = None


def override_engine(engine: AsyncEngine) -> None:  # pragma: no cover
    """Inject a pre-configured engine (for integration tests).

    After calling this, all ``get_session()`` / ``get_db()`` calls will use
    the provided engine instead of creating one from env vars.

    Also clears the session-factory cache so new sessions pick up the
    override immediately.
    """
    global _engine_override
    _engine_override = engine
    _get_session_factory.cache_clear()


def reset_engine() -> None:  # pragma: no cover
    """Reset to default engine (re-reads env vars on next call).

    Should be called in test teardown to avoid leaking state between
    test sessions.
    """
    global _engine_override
    _engine_override = None
    _get_engine.cache_clear()
    _get_session_factory.cache_clear()


# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _get_engine() -> AsyncEngine:
    """Create the async SQLAlchemy engine lazily on first use (cached singleton).

    If ``override_engine()`` was called, returns the override instead.
    """
    if _engine_override is not None:  # pragma: no cover — integration-tested
        return _engine_override
    settings = DatabaseSettings()
    return create_async_engine(
        settings.database_url,
        echo=os.getenv("SILVASONIC_SQL_ECHO", "False").lower() == "true",
        future=True,
        connect_args={"timeout": 5},  # asyncpg connect timeout (default: 60s)
        pool_timeout=5,  # Max wait for pool connection (default: 30s)
        pool_pre_ping=True,  # Detect stale connections before use
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


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI or other services to get a DB session."""
    async with _get_session_factory()() as session:  # pragma: no cover — integration-tested
        yield session


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Context manager for background tasks/scripts."""
    async with _get_session_factory()() as session:  # pragma: no cover — integration-tested
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
