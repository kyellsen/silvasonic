"""Pydantic settings for the Recorder service.

Reads configuration from ``SILVASONIC_*`` environment variables.
The optional ``SILVASONIC_RECORDER_CONFIG_JSON`` contains the full
Microphone Profile (serialized by the Controller, ADR-0016).
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from silvasonic.core.schemas.devices import MicrophoneProfile

log = structlog.get_logger()


class RecorderSettings(BaseSettings):
    """Recorder service configuration from environment variables.

    All fields are populated from ``SILVASONIC_*`` environment variables
    with sensible defaults for development.
    """

    model_config = SettingsConfigDict(env_prefix="SILVASONIC_")

    instance_id: str = "recorder"
    redis_url: str = "redis://localhost:6379/0"

    # Audio device (ALSA device string, injected by Controller)
    recorder_device: str = "hw:1,0"

    # Skip ALSA device validation (smoke tests without /dev/snd)
    skip_device_check: bool = False

    # Use synthetic audio source instead of real hardware (CI testing)
    recorder_mock_source: bool = False

    # Full profile config JSON (injected by Controller, ADR-0016)
    recorder_config_json: str | None = None

    # Workspace base path (bind-mounted by Controller)
    recorder_workspace: str = "/app/workspace"

    # FFmpeg configuration (ADR-0024)
    ffmpeg_binary: str = "ffmpeg"
    ffmpeg_loglevel: str = "warning"

    # Watchdog configuration (US-R06)
    recorder_watchdog_max_restarts: int = 5
    recorder_watchdog_check_interval_s: float = 5.0
    recorder_watchdog_stall_timeout_s: float = 60.0

    def parse_profile(self) -> MicrophoneProfile | None:
        """Parse ``recorder_config_json`` into a :class:`MicrophoneProfile`.

        Returns:
            Validated ``MicrophoneProfile`` or ``None`` if no config is set
            or parsing fails (best-effort — Recorder starts with defaults).
        """
        if not self.recorder_config_json:
            return None

        try:
            raw = json.loads(self.recorder_config_json)
        except json.JSONDecodeError:
            log.warning("settings.config_json_invalid", detail="JSON decode failed")
            return None

        # The Controller serializes profile.config which contains
        # audio/processing/stream sections but NOT the top-level
        # metadata (slug, name, etc.).  We need to provide required
        # fields to satisfy the MicrophoneProfile schema.
        if "slug" not in raw:
            raw["slug"] = "injected"
        if "name" not in raw:
            raw["name"] = "Injected Profile"
        if "audio" not in raw:
            log.warning("settings.config_json_no_audio", detail="Missing 'audio' section")
            return None

        try:
            return MicrophoneProfile(**raw)
        except ValidationError as exc:  # pragma: no cover — edge-case validation
            log.warning(
                "settings.config_json_validation_failed",
                errors=exc.error_count(),
            )
            return None

    @property
    def workspace_path(self) -> Path:
        """Return the workspace path as a ``Path`` object."""
        return Path(self.recorder_workspace)
