import os
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from silvasonic.core.settings import DatabaseSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Dev-mode fallback: allows module to work outside compose (e.g. local uv run).
# In production, compose x-db-env always provides SILVASONIC_DATABASE_URL.
os.environ.setdefault(
    "SILVASONIC_DATABASE_URL",
    "postgresql+asyncpg://postgres:password@silvasonic-database:5432/silvasonic",
)
settings = DatabaseSettings()  # type: ignore[call-arg]

# Create Async Engine
# echo=True can be enabled via env var if needed for debugging, keeping loose for now
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=os.getenv("SILVASONIC_SQL_ECHO", "False").lower() == "true",
    future=True,
)

# Create Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FASTAPI or other services to get a DB session."""
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Context manager for background tasks/scripts."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
