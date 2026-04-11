"""Janitor statistics and two-phase logging (v0.6.0)."""

from __future__ import annotations

import structlog
from silvasonic.core.constants import DEFAULT_LOG_STARTUP_S, DEFAULT_LOG_SUMMARY_INTERVAL_S
from silvasonic.core.two_phase import TwoPhaseWindow

log = structlog.get_logger()


class JanitorStats:
    """Tracks janitor progress and limits log spam during steady state."""

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

        self.total_deleted = 0
        self.total_errors = 0

        self._last_summary_deleted = 0
        self._last_summary_errors = 0

    @property
    def is_startup_phase(self) -> bool:
        """Return True if still in the initial verbose startup phase."""
        return self._window.is_startup_phase

    def record_deleted(
        self,
        recording_id: int,
        file_processed: str | None,
        mode: str,
        cloud_sync_fallback: bool,
    ) -> None:
        """Record a successfully deleted file."""
        self.total_deleted += 1
        if self.is_startup_phase:
            log.info(
                "janitor.deleted",
                recording_id=recording_id,
                file_processed=file_processed,
                mode=mode,
                cloud_sync_fallback=cloud_sync_fallback,
            )

    def record_error(self, recording_id: int, file_processed: str | None) -> None:
        """Record a deletion error."""
        self.total_errors += 1
        log.exception(
            "janitor.delete_error",
            recording_id=recording_id,
            file_processed=file_processed,
        )

    def maybe_emit_summary(
        self, mode: str, disk_usage_percent: float, cloud_sync_fallback: bool
    ) -> None:
        """Emit a periodic summary log if in steady state."""
        if self._window.consume_startup_transition():
            log.info(
                "janitor.startup_phase_complete",
                startup_duration_s=self._window._startup_duration_s,
                summary_interval_s=self._window._summary_interval_s,
            )

        if not self._window.is_summary_due():
            return

        elapsed = self._window.mark_summary_emitted()

        diff_deleted = self.total_deleted - self._last_summary_deleted
        diff_errors = self.total_errors - self._last_summary_errors

        if diff_deleted > 0 or diff_errors > 0:
            log.info(
                "janitor.summary",
                interval_s=round(elapsed, 1),
                mode=mode,
                disk_usage_percent=round(disk_usage_percent, 1),
                deleted_recent=diff_deleted,
                errors_recent=diff_errors,
                total_deleted=self.total_deleted,
                total_errors=self.total_errors,
                cloud_sync_fallback=cloud_sync_fallback,
            )

        self._last_summary_deleted = self.total_deleted
        self._last_summary_errors = self.total_errors

    def emit_final_summary(self) -> None:
        """Emit the lifetime summary before shutdown."""
        log.info(
            "janitor.shutdown",
            uptime_s=round(self._window.uptime_s, 1),
            total_deleted=self.total_deleted,
            total_errors=self.total_errors,
        )
