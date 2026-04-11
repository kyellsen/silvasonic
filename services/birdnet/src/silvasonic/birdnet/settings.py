from pydantic_settings import BaseSettings, SettingsConfigDict
from silvasonic.core.heartbeat import DEFAULT_HEARTBEAT_INTERVAL_S


class BirdnetEnvSettings(BaseSettings):
    """Environment configuration for the BirdNET background worker."""

    model_config = SettingsConfigDict(
        env_prefix="SILVASONIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    INSTANCE_ID: str = "birdnet"
    REDIS_URL: str = "redis://localhost:6379/0"
    HEARTBEAT_INTERVAL_S: float = DEFAULT_HEARTBEAT_INTERVAL_S
    WORKSPACE_DIR: str = "/data/birdnet"

    # Worker orchestration timings
    DB_RETRY_INTERVAL_S: float = 5.0
    POLLING_INTERVAL_S: float = 2.0

    # Path to Recorder workspace (mounted read-only from Controller)
    RECORDINGS_DIR: str = "/data/recorder"
