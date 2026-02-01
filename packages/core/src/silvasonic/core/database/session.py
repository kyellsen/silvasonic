import os
from collections.abc import AsyncGenerator

from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class DatabaseSettings(BaseSettings):  # type: ignore[misc]
    """Configuration settings for the database connection."""

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "silvasonic"
    POSTGRES_HOST: str = "database"  # Docker service name
    POSTGRES_PORT: int = 5432

    @property
    def database_url(self) -> str:
        """Construct and return the asynchronous database connection URL."""
        # asyncpg driver is required for Async operations
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


settings = DatabaseSettings()

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
