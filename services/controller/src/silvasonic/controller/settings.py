"""Pydantic settings for the Controller service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class ControllerSettings(BaseSettings):
    """Controller service configuration from environment variables.

    All fields are populated from ``SILVASONIC_*`` environment variables
    with sensible defaults for development.
    """

    model_config = SettingsConfigDict(env_prefix="SILVASONIC_")

    CONTROLLER_PORT: int = 9100
    REDIS_URL: str = "redis://localhost:6379/0"
