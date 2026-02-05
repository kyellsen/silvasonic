from pydantic import Field
from pydantic_settings import SettingsConfigDict
from silvasonic.core.settings import DatabaseSettings


class Settings(DatabaseSettings):
    """Configuration settings for the Status Board service."""

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    DEV_MODE: bool = False
    PORT: int = 8000

    REDIS_HOST: str = Field(default="silvasonic-redis", validation_alias="SILVASONIC_REDIS_HOST")
    REDIS_PORT: int = 6379

    # Container Engine
    PODMAN_SOCKET_PATH: str = "unix:///run/podman/podman.sock"

    @property
    def database_url(self) -> str:
        """Construct the PostgreSQL connection URL (Override or use parent)."""
        # Parent DatabaseSettings already has database_url property, but let's check if we need to override.
        # Parent uses self.POSTGRES_USER etc.
        # So we can simply inherit it!
        # Deleting this method to use parent's implementation if identical.
        return super().database_url


settings = Settings()  # type: ignore[call-arg]
