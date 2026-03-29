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

    # TCP port for the web UI (compose.yml exposes this)
    WEB_MOCK_PORT: int = 8001

    # Redis connection URL for heartbeat SSE and Pub/Sub
    REDIS_URL: str = "redis://redis:6379/0"

    # How often (seconds) to publish a heartbeat to Redis.
    # Range: 1-60.  Default 10.
    HEARTBEAT_INTERVAL_S: float = 10.0

    # Jinja2 template directory (auto-detected from package location)
    TEMPLATES_DIR: Path = _HERE / "templates"

    # Static assets directory (CSS, JS, images)
    STATIC_DIR: Path = _HERE / "static"
