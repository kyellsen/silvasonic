"""Pydantic settings for the Recorder service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class RecorderSettings(BaseSettings):
    """Recorder service configuration from environment variables.

    All fields are populated from ``SILVASONIC_*`` environment variables
    with sensible defaults for development.
    """

    model_config = SettingsConfigDict(env_prefix="SILVASONIC_")

    instance_id: str = "recorder"
    redis_url: str = "redis://localhost:6379/0"
