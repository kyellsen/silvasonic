from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class RecorderSettings(BaseSettings):
    """Configuration for the Silvasonic Recorder Service."""

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # Identity
    MIC_NAME: str = "default"
    MIC_PROFILE: str = "ultramic_384_evo"

    # Hardware
    # ALSA Device index can be explicitly set. If None, auto-detection logic (not implemented here) or default is used.
    ALSA_DEVICE_INDEX: int | None = None

    # Input Configuration (For Testing/Simulation)
    INPUT_FORMAT: str = "alsa"
    INPUT_DEVICE_OVERRIDE: str | None = None

    # Icecast Configuration
    ICECAST_HOST: str = "silvasonic-icecast"
    ICECAST_PORT: int = 8000
    ICECAST_USER: str = "source"
    ICECAST_PASSWORD: str
    ICECAST_MOUNT: str | None = None  # If None, defaults to /live/{MIC_NAME}.opus

    # Infrastructure
    LOG_DIR: Path | None = None

    # Redis (For Lifecycle/Status publishing)
    # Using the standard naming convention
    SILVASONIC_REDIS_HOST: str = "silvasonic-redis"

    @property
    def effective_mount(self) -> str:
        """Return the effective mount point."""
        if self.ICECAST_MOUNT:
            return self.ICECAST_MOUNT
        return f"/live/{self.MIC_NAME}.opus"

    @property
    def live_stream_url(self) -> str:
        """Construct the Icecast source URL."""
        return (
            f"icecast://{self.ICECAST_USER}:{self.ICECAST_PASSWORD}@"
            f"{self.ICECAST_HOST}:{self.ICECAST_PORT}{self.effective_mount}"
        )


settings = RecorderSettings()  # type: ignore[call-arg]
