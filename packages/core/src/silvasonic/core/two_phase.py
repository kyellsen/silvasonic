"""Two-Phase Logging Helper (ADR-0030).

Encapsulates time windows and phase transitions for the Two-Phase Logging
pattern (verbose startup followed by steady-state summaries). Designed as a
pure helper via Composition, avoiding Inheritance constraints on thread-locking
and state management.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from silvasonic.core.constants import DEFAULT_LOG_STARTUP_S, DEFAULT_LOG_SUMMARY_INTERVAL_S


class TwoPhaseWindow:
    """Tracks time windows for two-phase logging without managing locks or metrics.

    Provides pure boolean checks to determine if a service is still in its verbose
    startup phase, or if a steady-state summary interval has elapsed.
    """

    def __init__(
        self,
        startup_duration_s: float = DEFAULT_LOG_STARTUP_S,
        summary_interval_s: float = DEFAULT_LOG_SUMMARY_INTERVAL_S,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the TwoPhaseWindow.

        Args:
            startup_duration_s: Duration of the initial verbose phase.
            summary_interval_s: Interval between steady-state summaries.
            time_func: Dependency-injected clock function (defaults to monotonic).
        """
        self._time_func = time_func
        self._start_time = self._time_func()
        self._last_summary_time = self._start_time

        self._startup_duration_s = startup_duration_s
        self._summary_interval_s = summary_interval_s
        self._startup_ended_logged = False

    @property
    def is_startup_phase(self) -> bool:
        """Return True if currently within the initial startup duration."""
        return (self._time_func() - self._start_time) < self._startup_duration_s

    def consume_startup_transition(self) -> bool:
        """Evaluate if the startup phase just ended.

        Returns:
            True exactly once on the first call after the startup phase ends.
            False otherwise.
        """
        if not self.is_startup_phase and not self._startup_ended_logged:
            self._startup_ended_logged = True
            return True
        return False

    def is_summary_due(self) -> bool:
        """Return True if the summary interval has elapsed since the last summary."""
        return (self._time_func() - self._last_summary_time) >= self._summary_interval_s

    def mark_summary_emitted(self) -> float:
        """Reset the summary timer and return elapsed time.

        Returns:
            The exact elapsed time (in seconds) since the last summary omission.
        """
        now = self._time_func()
        elapsed = now - self._last_summary_time
        self._last_summary_time = now
        return elapsed

    @property
    def uptime_s(self) -> float:
        """Return the precise time elapsed since instantiation."""
        return self._time_func() - self._start_time
