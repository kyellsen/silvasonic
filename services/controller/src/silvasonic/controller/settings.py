from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ControllerSettings(BaseSettings):
    """Configuration for the Controller Service."""

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)

    # Podman Configuration
    PODMAN_SOCKET_URL: str = "unix:///run/podman/podman.sock"
    HOST_DATA_DIR: str = "/tmp/silvasonic_fallback"  # Workspace (Safe Default)
    HOST_SOURCE_DIR: str = "/mnt/data/dev/apps/silvasonic"  # Repository Root (Fallback)

    # Infrastructure
    REDIS_HOST: str = Field(default="silvasonic-redis", validation_alias="SILVASONIC_REDIS_HOST")
    ICECAST_HOST: str = "silvasonic-icecast"

    # Loop Configuration

    SYNC_INTERVAL_SECONDS: int = 2
