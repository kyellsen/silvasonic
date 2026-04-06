"""Database connection settings loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    POSTGRES_USER: str = "silvasonic"
    POSTGRES_PASSWORD: str = "silvasonic"
    POSTGRES_DB: str = "silvasonic"
    SILVASONIC_DB_HOST: str = "localhost"
    SILVASONIC_DB_PORT: int = 5432

    @property
    def database_url(self) -> str:
        """Construct the database URL from individual settings."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.SILVASONIC_DB_HOST}:{self.SILVASONIC_DB_PORT}/{self.POSTGRES_DB}"
        )

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)
