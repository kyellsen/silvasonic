"""Database session management with lazy initialization.

Engine and session factory are created on first use via ``@lru_cache``,
not at import time.  This eliminates import side-effects, improves
testability, and follows the Zen of Python: *Explicit is better than
implicit.*

In tests, call ``_get_engine.cache_clear()`` and
``_get_session_factory.cache_clear()`` to reset singletons between runs.
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


@lru_cache(maxsize=1)
def _get_engine() -> AsyncEngine:
    """Create the async SQLAlchemy engine lazily on first use (cached singleton)."""
    settings = DatabaseSettings()
    return create_async_engine(
        settings.database_url,
        echo=os.getenv("SILVASONIC_SQL_ECHO", "False").lower() == "true",
        future=True,
    )


@lru_cache(maxsize=1)
def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create the async session factory lazily on first use (cached singleton)."""
    return async_sessionmaker(
        bind=_get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI or other services to get a DB session."""
    async with _get_session_factory()() as session:
        yield session


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Context manager for background tasks/scripts."""
    async with _get_session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
