"""BirdNET statistics and two-phase logging (v0.8.0)."""

from __future__ import annotations

import structlog
from silvasonic.core.constants import DEFAULT_LOG_STARTUP_S, DEFAULT_LOG_SUMMARY_INTERVAL_S
from silvasonic.core.two_phase import TwoPhaseWindow

log = structlog.get_logger()


class BirdnetStats:
    """Tracks BirdNET inference progress and limits log spam during steady state."""

    def __init__(
        self,
        startup_duration_s: float = DEFAULT_LOG_STARTUP_S,
        summary_interval_s: float = DEFAULT_LOG_SUMMARY_INTERVAL_S,
    ) -> None:
        """Initialize the stats tracker."""
        self._window = TwoPhaseWindow(
            startup_duration_s=startup_duration_s,
            summary_interval_s=summary_interval_s,
        )

        self.total_analyzed = 0
        self.total_hits = 0
        self.total_errors = 0
        self.total_duration_s = 0.0

        self._last_summary_analyzed = 0
        self._last_summary_hits = 0
        self._last_summary_errors = 0

    @property
    def is_startup_phase(self) -> bool:
        """Return True if still in the initial verbose startup phase."""
        return self._window.is_startup_phase

    def record_analyzed(self, recording_id: int, duration: float, hits: int) -> None:
        """Record a successfully analyzed recording."""
        self.total_analyzed += 1
        self.total_hits += hits
        self.total_duration_s += duration

        if self.is_startup_phase:
            log.info(
                "birdnet.analyzed",
                recording_id=recording_id,
                duration_s=round(duration, 2),
                hits=hits,
            )

    def record_error(self, recording_id: int, exc: Exception) -> None:
        """Record an inference error."""
        self.total_errors += 1
        log.error(
            "birdnet.inference_error",
            recording_id=recording_id,
            error=str(exc),
        )

    def maybe_emit_summary(self) -> None:
        """Emit a periodic summary log if in steady state."""
        if self._window.consume_startup_transition():
            log.info(
                "birdnet.startup_phase_complete",
                startup_duration_s=self._window._startup_duration_s,
                summary_interval_s=self._window._summary_interval_s,
            )

        if not self._window.is_summary_due():
            return

        elapsed = self._window.mark_summary_emitted()

        diff_analyzed = self.total_analyzed - self._last_summary_analyzed
        diff_hits = self.total_hits - self._last_summary_hits
        diff_errors = self.total_errors - self._last_summary_errors

        if diff_analyzed > 0 or diff_errors > 0:
            log.info(
                "birdnet.summary",
                interval_s=round(elapsed, 1),
                analyzed_recent=diff_analyzed,
                hits_recent=diff_hits,
                errors_recent=diff_errors,
                total_analyzed=self.total_analyzed,
                total_hits=self.total_hits,
                total_errors=self.total_errors,
            )

        self._last_summary_analyzed = self.total_analyzed
        self._last_summary_hits = self.total_hits
        self._last_summary_errors = self.total_errors

    def emit_final_summary(self) -> None:
        """Emit the lifetime summary before shutdown."""
        log.info(
            "birdnet.shutdown",
            uptime_s=round(self._window.uptime_s, 1),
            total_analyzed=self.total_analyzed,
            total_hits=self.total_hits,
            total_errors=self.total_errors,
            total_duration_s=round(self.total_duration_s, 2),
        )
