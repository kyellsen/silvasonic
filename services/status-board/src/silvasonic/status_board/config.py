from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for the Status Board service."""

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    DEV_MODE: bool = False
    PORT: int = 8000

    # Database and Redis (defaults match compose)
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "silvasonic"
    POSTGRES_HOST: str = "silvasonic-database"
    POSTGRES_PORT: int = 5432

    REDIS_HOST: str = Field(default="silvasonic-redis", validation_alias="SILVASONIC_REDIS_HOST")
    REDIS_PORT: int = 6379

    # Container Engine
    PODMAN_SOCKET_PATH: str = "unix:///run/podman/podman.sock"

    @property
    def database_url(self) -> str:
        """Construct the PostgreSQL connection URL."""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


settings = Settings()
