"""Database location loaded from environment variables (ADR-0037)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DB_PATH = Path("/data/database/silvasonic.db")


class DatabaseSettings(BaseSettings):
    """Where the station database file lives.

    Every service with database access mounts the same host directory at
    the same path, so the default works inside every container.
    """

    SILVASONIC_DB_PATH: Path = DEFAULT_DB_PATH

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL of the database file (async ``aiosqlite`` driver)."""
        return f"sqlite+aiosqlite:///{self.SILVASONIC_DB_PATH}"

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)
