from pydantic_settings import BaseSettings, SettingsConfigDict


class ControllerSettings(BaseSettings):
    """Configuration for the Controller Service."""

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)

    # Podman Configuration
    PODMAN_SOCKET_URL: str = "unix:///run/podman/podman.sock"
    HOST_DATA_DIR: str = "/mnt/data/dev/apps/silvasonic"  # Workspace
    HOST_SOURCE_DIR: str = "/mnt/data/dev/apps/silvasonic"  # Repository Root (Fallback)

    # Loop Configuration

    SYNC_INTERVAL_SECONDS: int = 10
