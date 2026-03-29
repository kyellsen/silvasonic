"""Pydantic settings for the Controller service.

All fields read from ``SILVASONIC_*`` environment variables at startup.
See ``.env.example`` for documentation on each variable.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class ControllerSettings(BaseSettings):
    """Controller service configuration from environment variables.

    All fields are populated from ``SILVASONIC_*`` environment variables
    with sensible defaults for development.
    """

    model_config = SettingsConfigDict(env_prefix="SILVASONIC_")

    # --- Service Infrastructure ---

    # TCP port for the /healthy endpoint (compose.yml exposes this)
    CONTROLLER_PORT: int = 9100

    # Redis connection URL for heartbeats and Pub/Sub messaging
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Heartbeat ---

    # How often (seconds) to publish a heartbeat to Redis.
    # Lower = faster dashboard updates, higher = less Redis traffic.
    # Range: 1-60.  Default 10 is a good balance.
    HEARTBEAT_INTERVAL_S: float = 10.0

    # --- Reconciliation Loop ---

    # How often (seconds) the controller checks desired vs actual container state.
    # Lower = faster reaction to device changes, higher = less CPU.
    # Range: 0.5-10.  Default 1.0 is responsive without busy-looping.
    RECONCILE_INTERVAL_S: float = 1.0

    # --- Logging: Two-Phase Strategy ---
    # Phase 1 (Startup): Every event is logged individually for operator confidence.
    # Phase 2 (Steady State): Events are accumulated into periodic summaries.

    # Duration (seconds) of the detailed startup logging phase.
    # After this period, logging switches to periodic summaries.
    # Range: 60-600.  Default 300 (5 min) covers typical boot + first recording.
    CONTROLLER_LOG_STARTUP_S: float = 300.0

    # Interval (seconds) between steady-state log summaries.
    # Each summary includes reconciliation stats, container counts, and uptime.
    # Range: 60-3600.  Default 300 (5 min) provides regular visibility.
    CONTROLLER_LOG_SUMMARY_INTERVAL_S: float = 300.0

    # --- Background Monitor Intervals ---

    # How often (seconds) to check Database and Podman connectivity.
    # Range: 5-60.  Default 10 keeps dashboards responsive.
    CONTROLLER_MONITOR_POLL_INTERVAL_S: float = 10.0

    # How often (seconds) the LogForwarder polls for new/removed containers.
    # Range: 0.5-10.  Default 1.0 provides near real-time log streaming.
    LOG_FORWARDER_POLL_INTERVAL_S: float = 1.0
