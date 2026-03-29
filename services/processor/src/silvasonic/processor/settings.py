"""Processor service environment settings.

Infrastructure-level settings read from environment variables (Tier 1, .env).
Runtime-tunable settings (Janitor thresholds, Indexer intervals) are read
from the ``system_config`` table via ``ProcessorSettings`` (config_schemas.py)
on startup — see ``ProcessorService.load_config()``.
"""

from pydantic_settings import BaseSettings


class ProcessorEnvSettings(BaseSettings):
    """Environment variables for the Processor service.

    All fields are populated from ``SILVASONIC_*`` environment variables
    with sensible defaults for development.
    """

    model_config = {"env_prefix": "SILVASONIC_"}

    # --- Service Infrastructure ---

    # TCP port for the /healthy endpoint (compose.yml exposes this)
    PROCESSOR_PORT: int = 9200

    # Redis connection URL for heartbeats
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Heartbeat ---

    # How often (seconds) to publish a heartbeat to Redis.
    # Lower = faster dashboard updates, higher = less Redis traffic.
    # Range: 1-60.  Default 10 is a good balance.
    HEARTBEAT_INTERVAL_S: float = 10.0

    # --- Workspace Paths ---

    # Path to Recorder workspace (mounted read-write — Janitor delete authority)
    RECORDINGS_DIR: str = "/data/recorder"

    # Path to Processor workspace (read-write — internal state)
    PROCESSOR_DIR: str = "/data/processor"

    # --- Logging: Two-Phase Strategy ---
    # Phase 1 (Startup): Every event is logged individually.
    # Phase 2 (Steady State): Events are accumulated into periodic summaries.

    # Duration (seconds) of the detailed startup logging phase.
    # Range: 60-600.  Default 300 (5 min).
    PROCESSOR_LOG_STARTUP_S: float = 300.0

    # Interval (seconds) between steady-state log summaries.
    # Range: 60-3600.  Default 300 (5 min).
    PROCESSOR_LOG_SUMMARY_INTERVAL_S: float = 300.0
