from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    DATABASE_URL: str = "postgresql+asyncpg://silvasonic:silvasonic@localhost:5432/silvasonic"

    model_config = SettingsConfigDict(env_prefix="SILVASONIC_", case_sensitive=True)
