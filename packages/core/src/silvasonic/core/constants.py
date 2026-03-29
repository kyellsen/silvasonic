"""Shared timing constants for Silvasonic services.

Centralises values that are used identically across multiple modules
so they stay DRY and easy to find.
"""

from __future__ import annotations

RECONNECT_DELAY_S: float = 5.0
"""Seconds to wait before reconnecting after a Redis disconnection.

Used by NudgeSubscriber and LogForwarder in the Controller service.
"""
