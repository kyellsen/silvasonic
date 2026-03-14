"""Pydantic settings for the Recorder service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class RecorderSettings(BaseSettings):
    """Recorder service configuration from environment variables.

    All fields are populated from ``SILVASONIC_*`` environment variables
    with sensible defaults for development.
    """

    model_config = SettingsConfigDict(env_prefix="SILVASONIC_")

    INSTANCE_ID: str = "recorder"
    REDIS_URL: str = "redis://localhost:6379/0"
