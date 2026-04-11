"""Indexer statistics and two-phase logging (v0.6.0)."""

from __future__ import annotations

import structlog
from silvasonic.core.constants import DEFAULT_LOG_STARTUP_S, DEFAULT_LOG_SUMMARY_INTERVAL_S
from silvasonic.core.two_phase import TwoPhaseWindow

log = structlog.get_logger()


class IndexerStats:
    """Tracks indexer progress and limits log spam during steady state."""

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

        self.total_indexed = 0
        self.total_errors = 0
        self.total_skipped = 0

        self._last_summary_indexed = 0
        self._last_summary_errors = 0

    @property
    def is_startup_phase(self) -> bool:
        """Return True if still in the initial verbose startup phase."""
        return self._window.is_startup_phase

    def record_indexed(self, rel_path: str, sensor_id: str, duration: float) -> None:
        """Record a successfully indexed file."""
        self.total_indexed += 1
        if self.is_startup_phase:
            log.info(
                "indexer.indexed",
                file=rel_path,
                sensor_id=sensor_id,
                duration=duration,
            )

    def record_error(self, rel_path: str) -> None:
        """Record an indexing error."""
        self.total_errors += 1
        log.exception("indexer.error", file=rel_path)

    def record_skipped(self) -> None:
        """Record a skipped file (idempotent ignore or blacklisted)."""
        self.total_skipped += 1

    def maybe_emit_summary(self) -> None:
        """Emit a periodic summary log if in steady state."""
        if self._window.consume_startup_transition():
            log.info(
                "indexer.startup_phase_complete",
                startup_duration_s=self._window._startup_duration_s,
                summary_interval_s=self._window._summary_interval_s,
            )

        if not self._window.is_summary_due():
            return

        elapsed = self._window.mark_summary_emitted()

        diff_indexed = self.total_indexed - self._last_summary_indexed
        diff_errors = self.total_errors - self._last_summary_errors

        if diff_indexed > 0 or diff_errors > 0:
            log.info(
                "indexer.summary",
                interval_s=round(elapsed, 1),
                indexed_recent=diff_indexed,
                errors_recent=diff_errors,
                total_indexed=self.total_indexed,
                total_errors=self.total_errors,
                total_skipped=self.total_skipped,
            )

        self._last_summary_indexed = self.total_indexed
        self._last_summary_errors = self.total_errors

    def emit_final_summary(self) -> None:
        """Emit the lifetime summary before shutdown."""
        log.info(
            "indexer.shutdown",
            uptime_s=round(self._window.uptime_s, 1),
            total_indexed=self.total_indexed,
            total_errors=self.total_errors,
            total_skipped=self.total_skipped,
        )
