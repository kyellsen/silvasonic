import os
from collections.abc import AsyncGenerator

from silvasonic.core.settings import DatabaseSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

settings = DatabaseSettings()  # type: ignore[call-arg]

# Create Async Engine
# echo=True can be enabled via env var if needed for debugging, keeping loose for now
engine = create_async_engine(
    settings.database_url, echo=os.getenv("SQL_ECHO", "False").lower() == "true", future=True
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
