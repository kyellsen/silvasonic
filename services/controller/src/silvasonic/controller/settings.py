from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ControllerSettings(BaseSettings):
    """Configuration for the Controller Service."""

    model_config = SettingsConfigDict(
        env_prefix="", case_sensitive=True, env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    # Podman Configuration
    PODMAN_SOCKET_URL: str
    HOST_DATA_DIR: str  # Workspace
    LOCAL_DATA_DIR: str | None = None  # Internal Workspace Path (if different from Host)
    HOST_SOURCE_DIR: str  # Repository Root

    # Infrastructure
    REDIS_HOST: str = Field(default="silvasonic-redis", validation_alias="SILVASONIC_REDIS_HOST")
    ICECAST_HOST: str = "silvasonic-icecast"
    ICECAST_PASSWORD: str

    # Orchestration
    PODMAN_NETWORK_NAME: str = "silvasonic_silvasonic-net"  # Default for 'silvasonic' dir

    # Loop Configuration

    # Loop Configuration
    PROFILES_DIR: str = "/etc/silvasonic/profiles"
    SYNC_INTERVAL_SECONDS: int = 2
