"""Pydantic settings for the Recorder service.

Reads configuration from ``SILVASONIC_*`` environment variables.
The optional ``SILVASONIC_RECORDER_CONFIG_JSON`` contains the
controller-injected runtime config (audio/processing/stream sections,
serialized from ``MicrophoneProfile.config`` JSONB by the Controller,
ADR-0016).
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from silvasonic.recorder.schemas import InjectedRecorderConfig

log = structlog.get_logger()


class RecorderSettings(BaseSettings):
    """Recorder service configuration from environment variables.

    All fields are populated from ``SILVASONIC_*`` environment variables
    with sensible defaults for development.
    """

    model_config = SettingsConfigDict(env_prefix="SILVASONIC_")

    # --- Service Infrastructure ---

    INSTANCE_ID: str = "recorder"
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Heartbeat ---

    # How often (seconds) to publish a heartbeat to Redis.
    # Lower = faster dashboard updates, higher = less Redis traffic.
    # Range: 1-60.  Default 10 is a good balance.
    HEARTBEAT_INTERVAL_S: float = 10.0

    # --- Audio Device ---

    # ALSA device string (injected by Controller, e.g. "hw:2,0").
    RECORDER_DEVICE: str = "hw:1,0"

    # Use synthetic audio source (lavfi sine) instead of real hardware (CI testing).
    RECORDER_MOCK_SOURCE: bool = False

    # Full microphone profile as JSON string (injected by Controller, ADR-0016).
    # Contains audio/processing/stream sections with sample rate, gain, etc.
    RECORDER_CONFIG_JSON: str | None = None

    # Workspace base path (bind-mounted by Controller).
    RECORDER_WORKSPACE: str = "/app/workspace"

    # --- FFmpeg (ADR-0024) ---

    # Path to the FFmpeg binary
    FFMPEG_BINARY: str = "ffmpeg"
    # FFmpeg log verbosity.
    # Values: "quiet", "panic", "fatal", "error", "warning", "info", "verbose", "debug"
    FFMPEG_LOGLEVEL: str = "warning"

    # --- Watchdog (US-R06) ---
    # The watchdog monitors FFmpeg health and restarts it on failure.
    # After max_restarts consecutive failures, the watchdog gives up
    # and the container restart policy (Level 2 recovery) takes over.

    # Maximum consecutive restart attempts before giving up.  Range: 1-20.
    RECORDER_WATCHDOG_MAX_RESTARTS: int = 5
    # Seconds between health checks (crash + stall detection).  Range: 1-30.
    RECORDER_WATCHDOG_CHECK_INTERVAL_S: float = 5.0
    # Seconds without new segments before declaring a stall.  Range: 30-300.
    RECORDER_WATCHDOG_STALL_TIMEOUT_S: float = 60.0
    # Base delay (seconds) for exponential backoff between restart attempts.
    # Actual delay = base_backoff * 2^(attempt-1).  Range: 0.5-10.
    RECORDER_WATCHDOG_BASE_BACKOFF_S: float = 2.0

    # --- Logging: Two-Phase Strategy ---
    # Phase 1 (Startup): Every segment promotion is logged individually.
    # Phase 2 (Steady State): Promotions are accumulated into periodic summaries.

    # Duration (seconds) of the detailed startup logging phase.
    # Range: 60-600.  Default 300 (5 min) covers ~20 segments at 15s rotation.
    RECORDER_LOG_STARTUP_S: float = 300.0
    # Interval (seconds) between steady-state log summaries.
    # Range: 60-3600.  Default 300 (5 min) provides regular throughput visibility.
    RECORDER_LOG_SUMMARY_INTERVAL_S: float = 300.0

    # --- Health Monitor ---
    # How often (seconds) to check pipeline status (active/exited).
    # Range: 1-30.  Default 5 provides quick failure detection without busy-looping.
    RECORDER_HEALTH_POLL_INTERVAL_S: float = 5.0

    def parse_injected_config(self) -> InjectedRecorderConfig | None:
        """Parse ``RECORDER_CONFIG_JSON`` into an :class:`InjectedRecorderConfig`.

        Returns:
            Validated ``InjectedRecorderConfig`` or ``None`` if no config
            is set or parsing fails (best-effort — Recorder starts with
            defaults).
        """
        if not self.RECORDER_CONFIG_JSON:
            return None

        try:
            raw = json.loads(self.RECORDER_CONFIG_JSON)
        except json.JSONDecodeError:
            log.warning("settings.config_json_invalid", detail="JSON decode failed")
            return None

        if "audio" not in raw:
            log.warning("settings.config_json_no_audio", detail="Missing 'audio' section")
            return None

        try:
            return InjectedRecorderConfig(**raw)
        except ValidationError as exc:  # pragma: no cover — edge-case validation
            log.warning(
                "settings.config_json_validation_failed",
                errors=exc.error_count(),
            )
            return None

    @property
    def workspace_path(self) -> Path:
        """Return the workspace path as a ``Path`` object."""
        return Path(self.RECORDER_WORKSPACE)
