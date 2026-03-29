"""Controller statistics tracker for production logging.

Two-phase logging strategy (mirrors Recorder's RecordingStats):

  - **Startup Phase** (configurable, default 5 min): Log every container
    action, device change, and reconciliation event individually.
  - **Steady State**: Accumulate stats and emit a single summary log
    every ``summary_interval_s`` seconds (default 5 min).

The summary includes:
  - Running containers (count + names)
  - Online/offline device counts
  - Reconciliation cycle count + errors
  - Container start/stop actions since last summary
  - DB and Podman connectivity
  - Nudge count
  - Uptime

Design:
  - Thread-safe (reconciler runs in to_thread)
  - No internal timer — caller polls ``get_summary_if_due()``
  - structlog-native JSON output
"""

from __future__ import annotations

import threading
import time

import structlog

log = structlog.get_logger()

# Default phase thresholds (overridable via envvars)
DEFAULT_STARTUP_DURATION_S: float = 300.0  # 5 minutes
DEFAULT_SUMMARY_INTERVAL_S: float = 300.0  # 5 minutes


class ControllerStats:
    """Track controller operations and emit structured log summaries.

    Thread-safe — ``record_*`` methods may be called from ``asyncio.to_thread``
    workers (reconciler, container manager) concurrently with the async
    main loop.

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
        self._total_reconcile_cycles: int = 0
        self._total_reconcile_errors: int = 0
        self._total_containers_started: int = 0
        self._total_containers_stopped: int = 0
        self._total_nudges: int = 0

        # Per-interval counters (reset each summary)
        self._interval_reconcile_cycles: int = 0
        self._interval_reconcile_errors: int = 0
        self._interval_containers_started: int = 0
        self._interval_containers_stopped: int = 0
        self._interval_nudges: int = 0
        self._last_summary_time: float = self._start_time

        # Container action log (names started/stopped in this interval)
        self._interval_started_names: list[str] = []
        self._interval_stopped_names: list[str] = []

        # Phase transition flag
        self._startup_ended_logged = False

    @property
    def in_startup_phase(self) -> bool:
        """Return ``True`` if still in the detailed startup phase."""
        return (time.monotonic() - self._start_time) < self._startup_duration_s

    # ------------------------------------------------------------------
    # Record methods (thread-safe)
    # ------------------------------------------------------------------

    def record_reconcile_cycle(self) -> None:
        """Record a completed reconciliation cycle."""
        with self._lock:
            self._total_reconcile_cycles += 1
            self._interval_reconcile_cycles += 1

    def record_reconcile_error(self) -> None:
        """Record a reconciliation cycle failure."""
        with self._lock:
            self._total_reconcile_errors += 1
            self._interval_reconcile_errors += 1

    def record_container_start(self, name: str) -> None:
        """Record a container start action.

        During startup: also logs individually.
        """
        with self._lock:
            self._total_containers_started += 1
            self._interval_containers_started += 1
            self._interval_started_names.append(name)

        if self.in_startup_phase:
            log.info("controller.container_started", name=name)

    def record_container_stop(self, name: str) -> None:
        """Record a container stop action.

        During startup: also logs individually.
        """
        with self._lock:
            self._total_containers_stopped += 1
            self._interval_containers_stopped += 1
            self._interval_stopped_names.append(name)

        if self.in_startup_phase:
            log.info("controller.container_stopped", name=name)

    def record_nudge(self) -> None:
        """Record a received nudge message."""
        with self._lock:
            self._total_nudges += 1
            self._interval_nudges += 1

    # ------------------------------------------------------------------
    # Summary emission
    # ------------------------------------------------------------------

    def get_summary_if_due(self) -> dict[str, object] | None:
        """Return interval stats if the summary interval has elapsed.

        Returns ``None`` if the interval has not elapsed yet.
        The caller is responsible for enriching the summary with
        live data (container list, DB/Podman status) and logging it.

        Resets interval counters on each emission.
        """
        now = time.monotonic()

        # Check phase transition
        if not self.in_startup_phase and not self._startup_ended_logged:
            self._startup_ended_logged = True
            with self._lock:
                total_cycles = self._total_reconcile_cycles
                total_errors = self._total_reconcile_errors
            log.info(
                "controller.startup_phase_complete",
                startup_duration_s=self._startup_duration_s,
                total_reconcile_cycles=total_cycles,
                total_reconcile_errors=total_errors,
                summary_interval_s=self._summary_interval_s,
            )

        with self._lock:
            elapsed = now - self._last_summary_time
            if elapsed < self._summary_interval_s:
                return None

            # Snapshot and reset
            summary: dict[str, object] = {
                "interval_s": round(elapsed, 1),
                "interval_reconcile_cycles": self._interval_reconcile_cycles,
                "interval_reconcile_errors": self._interval_reconcile_errors,
                "interval_containers_started": self._interval_containers_started,
                "interval_containers_stopped": self._interval_containers_stopped,
                "interval_started_names": list(self._interval_started_names),
                "interval_stopped_names": list(self._interval_stopped_names),
                "interval_nudges": self._interval_nudges,
                "total_reconcile_cycles": self._total_reconcile_cycles,
                "total_reconcile_errors": self._total_reconcile_errors,
                "total_containers_started": self._total_containers_started,
                "total_containers_stopped": self._total_containers_stopped,
                "total_nudges": self._total_nudges,
                "uptime_s": round(now - self._start_time, 0),
            }

            # Reset interval
            self._interval_reconcile_cycles = 0
            self._interval_reconcile_errors = 0
            self._interval_containers_started = 0
            self._interval_containers_stopped = 0
            self._interval_nudges = 0
            self._interval_started_names = []
            self._interval_stopped_names = []
            self._last_summary_time = now

        return summary

    def emit_final_summary(self) -> None:
        """Emit a final summary at shutdown."""
        now = time.monotonic()
        with self._lock:
            log.info(
                "controller.final_summary",
                total_reconcile_cycles=self._total_reconcile_cycles,
                total_reconcile_errors=self._total_reconcile_errors,
                total_containers_started=self._total_containers_started,
                total_containers_stopped=self._total_containers_stopped,
                total_nudges=self._total_nudges,
                uptime_s=round(now - self._start_time, 0),
                pending_cycles_since_last_summary=self._interval_reconcile_cycles,
            )
