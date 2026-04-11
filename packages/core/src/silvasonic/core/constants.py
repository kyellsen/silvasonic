"""Shared timing constants for Silvasonic services.

Centralises values that are used identically across multiple modules
so they stay DRY and easy to find.
"""

from __future__ import annotations

RECONNECT_DELAY_S: float = 5.0
"""Seconds to wait before reconnecting after a Redis disconnection.

Used by NudgeSubscriber and LogForwarder in the Controller service.
"""

DEFAULT_LOG_STARTUP_S: float = 300.0
"""Default duration (seconds) for the initial verbose logging phase (Two-Phase Logging)."""

DEFAULT_LOG_SUMMARY_INTERVAL_S: float = 300.0
"""Default interval (seconds) for steady-state summary logs (Two-Phase Logging)."""
