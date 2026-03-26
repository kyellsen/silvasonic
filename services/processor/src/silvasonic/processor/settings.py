"""Processor service environment settings.

Infrastructure-level settings read from environment variables (Tier 1, .env).
Runtime-tunable settings (Janitor thresholds, Indexer intervals) are read
from the ``system_config`` table via ``ProcessorSettings`` (config_schemas.py)
on startup — see ``ProcessorService.load_config()``.
"""

from pydantic_settings import BaseSettings


class ProcessorEnvSettings(BaseSettings):
    """Environment variables for the Processor service.

    Attributes:
        PROCESSOR_PORT: Health endpoint port (default 9200).
        REDIS_URL: Redis connection URL for heartbeats.
    """

    PROCESSOR_PORT: int = 9200
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = {"env_prefix": "SILVASONIC_"}
