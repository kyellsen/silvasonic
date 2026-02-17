import os
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from silvasonic.core.settings import DatabaseSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# In production, compose env vars provide the necessary POSTGRES_* values.
settings = DatabaseSettings()

# Create Async Engine
# echo=True can be enabled via env var if needed for debugging, keeping loose for now
engine = create_async_engine(
    settings.database_url,
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
