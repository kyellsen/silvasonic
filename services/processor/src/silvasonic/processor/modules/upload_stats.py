"""Upload statistics and two-phase logging (v0.6.0).

Follows the same Two-Phase Logging pattern as the Recorder:
1. Startup Phase (default 5min): Every upload attempt is logged individually.
2. Steady State: Periodic summary logs every 5 minutes.
"""

from __future__ import annotations

import time

import structlog

log = structlog.get_logger()


class UploadStats:
    """Tracks upload progress and limits log spam during steady state."""

    def __init__(
        self, startup_duration_s: float = 300.0, summary_interval_s: float = 300.0
    ) -> None:
        """Initialize the stats tracker.

        Args:
            startup_duration_s: How long individual uploads are logged.
            summary_interval_s: How often summary is printed in steady state.
        """
        self._start_time = time.monotonic()
        self._startup_duration_s = startup_duration_s
        self._summary_interval_s = summary_interval_s

        self.total_pending = 0
        self.uploaded_count = 0
        self.failed_count = 0
        self.bytes_transferred = 0
        self.last_upload_at: float | None = None

        self._last_summary_time = self._start_time
        self._last_summary_uploaded = 0
        self._last_summary_failed = 0
        self._last_summary_bytes = 0

    @property
    def _is_startup_phase(self) -> bool:
        """Return True if still in the initial verbose startup phase."""
        return time.monotonic() - self._start_time < self._startup_duration_s

    def update_pending(self, count: int) -> None:
        """Update the known number of pending uploads."""
        self.total_pending = count

    def record_attempt(
        self, success: bool, bytes_transferred: int, source: str, target: str, duration: float
    ) -> None:
        """Record an upload attempt and emit logs if appropriate."""
        if success:
            self.uploaded_count += 1
            self.bytes_transferred += bytes_transferred
            self.last_upload_at = time.time()
            if self._is_startup_phase:
                log.info(
                    "upload_worker.success",
                    source=source,
                    target=target,
                    size=bytes_transferred,
                    duration=round(duration, 2),
                )
        else:
            self.failed_count += 1
            # Failures are always logged by the rclone client, but we might want a brief note here
            if self._is_startup_phase:
                log.warning("upload_worker.failed", source=source, duration=round(duration, 2))

        self._maybe_emit_summary()

    def _maybe_emit_summary(self) -> None:
        """Emit a periodic summary log if in steady state."""
        now = time.monotonic()
        if now - self._last_summary_time >= self._summary_interval_s:
            # We don't emit if nothing happened
            diff_success = self.uploaded_count - self._last_summary_uploaded
            diff_fail = self.failed_count - self._last_summary_failed

            if diff_success > 0 or diff_fail > 0:
                mb_transferred = (self.bytes_transferred - self._last_summary_bytes) / (1024 * 1024)

                log.info(
                    "upload_worker.summary",
                    uploaded_recent=diff_success,
                    failed_recent=diff_fail,
                    mb_transferred=round(mb_transferred, 2),
                    total_uploaded=self.uploaded_count,
                    total_failed=self.failed_count,
                    total_pending=self.total_pending,
                )

            self._last_summary_time = now
            self._last_summary_uploaded = self.uploaded_count
            self._last_summary_failed = self.failed_count
            self._last_summary_bytes = self.bytes_transferred

    def emit_final_summary(self) -> None:
        """Emit the lifetime summary before shutdown."""
        running_time_s = time.monotonic() - self._start_time
        mb_total = self.bytes_transferred / (1024 * 1024)

        log.info(
            "upload_worker.shutdown",
            uptime_s=round(running_time_s, 1),
            total_uploaded=self.uploaded_count,
            total_failed=self.failed_count,
            total_mb_transferred=round(mb_total, 2),
            remaining_pending=self.total_pending,
        )
