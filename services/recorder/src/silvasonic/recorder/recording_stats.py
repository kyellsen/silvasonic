"""Recording statistics tracker for production logging.

Two-phase logging strategy for long-term monitoring:

  - **Startup Phase** (configurable, default 5 min): Log every segment
    promotion individually with full metadata (filename, size, stream).
    Builds operator confidence that capture is working correctly.

  - **Steady State**: Accumulate stats and emit a single summary log
    every ``summary_interval_s`` seconds (default 5 min).  Includes
    per-interval and lifetime counters plus file-size statistics.

Design:
    - Thread-safe — called from ``SegmentPromoter`` threads
    - Zero-alloc hot path — counters are plain ints under a lock
    - structlog-native — all output is JSON-structured
    - Errors are ALWAYS logged individually regardless of phase
"""

from __future__ import annotations

import threading
import time

import structlog

log = structlog.get_logger()

# Default phase thresholds (overridable via envvars)
DEFAULT_STARTUP_DURATION_S: float = 300.0  # 5 minutes
DEFAULT_SUMMARY_INTERVAL_S: float = 300.0  # 5 minutes


class RecordingStats:
    """Track segment promotions and emit structured log summaries.

    Thread-safe — called from ``SegmentPromoter`` threads running
    concurrently for raw and processed streams.

    Args:
        startup_duration_s: Duration of the detailed startup phase.
        summary_interval_s: Interval between steady-state summaries.
    """

    def __init__(
        self,
        *,
        startup_duration_s: float = DEFAULT_STARTUP_DURATION_S,
        summary_interval_s: float = DEFAULT_SUMMARY_INTERVAL_S,
    ) -> None:
        """Initialize the stats tracker."""
        self._lock = threading.Lock()
        self._start_time = time.monotonic()
        self._startup_duration_s = startup_duration_s
        self._summary_interval_s = summary_interval_s

        # Lifetime counters
        self._total_promoted: int = 0
        self._total_bytes: int = 0
        self._total_errors: int = 0

        # Per-summary-interval counters (reset each summary)
        self._interval_promoted: int = 0
        self._interval_bytes: int = 0
        self._interval_errors: int = 0
        self._last_summary_time: float = self._start_time

        # File-size tracking (per interval, reset each summary)
        self._interval_size_min: int | None = None
        self._interval_size_max: int = 0
        self._interval_size_sum: int = 0

        # Per-stream counters (lifetime)
        self._stream_promoted: dict[str, int] = {}
        self._stream_bytes: dict[str, int] = {}

        # Phase transition flag (logged once)
        self._startup_ended_logged = False

    @property
    def in_startup_phase(self) -> bool:
        """Return ``True`` if still in the detailed startup phase."""
        return (time.monotonic() - self._start_time) < self._startup_duration_s

    def record_promotion(
        self,
        stream: str,
        filename: str,
        file_size_bytes: int,
    ) -> None:
        """Record a successful segment promotion.

        During startup phase: logs every segment individually with metadata.
        During steady state: accumulates for periodic summary.

        Args:
            stream: Stream name (``"raw"`` or ``"processed"``).
            filename: WAV filename that was promoted.
            file_size_bytes: Size of the promoted file in bytes.
        """
        with self._lock:
            self._total_promoted += 1
            self._total_bytes += file_size_bytes
            self._interval_promoted += 1
            self._interval_bytes += file_size_bytes

            # File-size tracking
            self._interval_size_sum += file_size_bytes
            if self._interval_size_min is None or file_size_bytes < self._interval_size_min:
                self._interval_size_min = file_size_bytes
            if file_size_bytes > self._interval_size_max:
                self._interval_size_max = file_size_bytes

            # Per-stream
            self._stream_promoted[stream] = self._stream_promoted.get(stream, 0) + 1
            self._stream_bytes[stream] = self._stream_bytes.get(stream, 0) + file_size_bytes

            total = self._total_promoted

        if self.in_startup_phase:
            log.info(
                "segment.promoted",
                stream=stream,
                filename=filename,
                size_bytes=file_size_bytes,
                total=total,
            )
        else:
            self._check_phase_transition()
            self._maybe_emit_summary()

    def record_error(self, stream: str, filename: str) -> None:
        """Record a failed segment promotion.

        Errors are ALWAYS logged individually regardless of phase.

        Args:
            stream: Stream name.
            filename: WAV filename that failed.
        """
        with self._lock:
            self._total_errors += 1
            self._interval_errors += 1
            total_errors = self._total_errors

        log.error(
            "segment.promote_failed",
            stream=stream,
            filename=filename,
            total_errors=total_errors,
        )

    def _check_phase_transition(self) -> None:
        """Log once when transitioning from startup to steady state."""
        if self._startup_ended_logged:
            return

        self._startup_ended_logged = True
        with self._lock:
            total = self._total_promoted
            errors = self._total_errors

        log.info(
            "recording.startup_phase_complete",
            startup_duration_s=self._startup_duration_s,
            total_promoted=total,
            total_errors=errors,
            summary_interval_s=self._summary_interval_s,
        )

    def _maybe_emit_summary(self) -> None:
        """Emit a summary log if the interval has elapsed."""
        now = time.monotonic()
        with self._lock:
            elapsed = now - self._last_summary_time
            if elapsed < self._summary_interval_s:
                return

            # Snapshot and reset interval counters
            interval_promoted = self._interval_promoted
            interval_bytes = self._interval_bytes
            interval_errors = self._interval_errors
            size_min = self._interval_size_min
            size_max = self._interval_size_max
            size_sum = self._interval_size_sum
            total_promoted = self._total_promoted
            total_bytes = self._total_bytes
            total_errors = self._total_errors
            streams = dict(self._stream_promoted)
            uptime_s = round(now - self._start_time, 0)

            # Reset interval counters
            self._interval_promoted = 0
            self._interval_bytes = 0
            self._interval_errors = 0
            self._interval_size_min = None
            self._interval_size_max = 0
            self._interval_size_sum = 0
            self._last_summary_time = now

        # Compute derived metrics outside lock
        interval_s = round(elapsed, 1)
        rate_mb_h = (interval_bytes / 1_048_576) / (elapsed / 3600) if elapsed > 0 else 0.0
        size_avg = size_sum // interval_promoted if interval_promoted > 0 else 0

        log.info(
            "recording.summary",
            interval_promoted=interval_promoted,
            interval_errors=interval_errors,
            interval_s=interval_s,
            rate_mb_h=round(rate_mb_h, 1),
            size_min_bytes=size_min if size_min is not None else 0,
            size_max_bytes=size_max,
            size_avg_bytes=size_avg,
            total_promoted=total_promoted,
            total_bytes=total_bytes,
            total_errors=total_errors,
            uptime_s=uptime_s,
            streams=streams,
        )

    def emit_final_summary(self) -> None:
        """Emit a final summary at shutdown.

        Always logged — provides the definitive session statistics.
        """
        now = time.monotonic()
        with self._lock:
            total_promoted = self._total_promoted
            total_bytes = self._total_bytes
            total_errors = self._total_errors
            uptime_s = round(now - self._start_time, 0)
            streams = dict(self._stream_promoted)
            stream_bytes = dict(self._stream_bytes)

            # Include any un-emitted interval data
            pending_promoted = self._interval_promoted
            pending_errors = self._interval_errors

        log.info(
            "recording.final_summary",
            total_promoted=total_promoted,
            total_bytes=total_bytes,
            total_errors=total_errors,
            uptime_s=uptime_s,
            streams=streams,
            stream_bytes=stream_bytes,
            pending_since_last_summary=pending_promoted,
            pending_errors_since_last_summary=pending_errors,
        )
