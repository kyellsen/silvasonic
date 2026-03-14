"""Pydantic settings for the Web-Mock service."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_HERE = Path(__file__).parent


class WebMockSettings(BaseSettings):
    """Web-Mock service configuration from environment variables.

    All fields are populated from ``SILVASONIC_*`` environment variables
    with sensible defaults for development.
    """

    model_config = SettingsConfigDict(env_prefix="SILVASONIC_")

    WEB_MOCK_PORT: int = 8001
    REDIS_URL: str = "redis://redis:6379/0"
    TEMPLATES_DIR: Path = _HERE / "templates"
    STATIC_DIR: Path = _HERE / "static"
