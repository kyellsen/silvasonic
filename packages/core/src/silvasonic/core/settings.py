from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):  # type: ignore[misc]
    """Configuration settings for the database connection."""

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str = "silvasonic"
    POSTGRES_HOST: str = "database"  # Docker service name
    POSTGRES_PORT: int = 5432

    @property
    def database_url(self) -> str:
        """Construct and return the asynchronous database connection URL."""
        # asyncpg driver is required for Async operations
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
