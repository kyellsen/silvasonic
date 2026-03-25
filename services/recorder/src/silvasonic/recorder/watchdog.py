"""Recording Watchdog — automatic FFmpeg pipeline recovery (US-R06).

Monitors the FFmpeg subprocess managed by :class:`FFmpegPipeline` and
restarts it on failure with exponential backoff.  This is **Level 1** of the
multi-level recovery strategy documented in the Recorder README:

    Level 1: Watchdog restarts FFmpeg *within* the container
    Level 2: Podman ``restart: on-failure`` restarts the container
    Level 3: Controller reconciliation recreates unresponsive containers

The Watchdog detects three failure modes:

    1. **Crash** — FFmpeg process exited (``is_active`` is ``False``)
    2. **Stall** — No new segments promoted within ``stall_timeout_s``
    3. **Start failure** — ``pipeline.start()`` raises an exception

After ``max_restarts`` consecutive failures the Watchdog gives up and
exits, allowing Level 2 (container restart) to take over.

Design:
    - Pure async — no threads, integrates with SilvaService's event loop
    - Takes ``FFmpegPipeline`` as dependency (composition, not inheritance)
    - Cooperates with ``shutdown_event`` for graceful shutdown
    - Backoff resets if the pipeline runs successfully for a full check cycle
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from silvasonic.recorder.ffmpeg_pipeline import FFmpegPipeline

log = structlog.get_logger()


class RecordingWatchdog:
    """Monitor FFmpeg pipeline health and restart on failure.

    Args:
        pipeline: The ``FFmpegPipeline`` instance to monitor.
        max_restarts: Maximum consecutive restart attempts before giving up.
        check_interval_s: Seconds between health checks.
        stall_timeout_s: Seconds without new segments before declaring a stall.
        base_backoff_s: Base delay for exponential backoff (doubles each retry).
    """

    def __init__(
        self,
        pipeline: FFmpegPipeline,
        *,
        max_restarts: int = 5,
        check_interval_s: float = 5.0,
        stall_timeout_s: float = 60.0,
        base_backoff_s: float = 2.0,
    ) -> None:
        """Initialize the watchdog (does NOT start monitoring)."""
        self._pipeline = pipeline
        self._max_restarts = max_restarts
        self._check_interval_s = check_interval_s
        self._stall_timeout_s = stall_timeout_s
        self._base_backoff_s = base_backoff_s

        self._restart_count = 0
        self._giving_up = False
        self._last_failure_reason: str | None = None

        # Stall detection state
        self._last_segment_count = 0
        self._last_segment_change_s: float = 0.0

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def restart_count(self) -> int:
        """Number of restarts performed so far."""
        return self._restart_count

    @property
    def max_restarts(self) -> int:
        """Maximum allowed restarts."""
        return self._max_restarts

    @property
    def is_giving_up(self) -> bool:
        """``True`` if the watchdog has exhausted all restart attempts."""
        return self._giving_up

    @property
    def last_failure_reason(self) -> str | None:
        """Human-readable description of the last detected failure."""
        return self._last_failure_reason

    # ------------------------------------------------------------------
    # Main watch loop
    # ------------------------------------------------------------------

    async def watch(self, shutdown_event: asyncio.Event) -> None:
        """Monitor the pipeline and restart on failure.

        Exits when:
        - ``shutdown_event`` is set (graceful shutdown)
        - ``max_restarts`` consecutive failures exceeded (giving up)

        Args:
            shutdown_event: Set by ``SilvaService`` on SIGTERM/SIGINT.
        """
        loop = asyncio.get_event_loop()
        self._last_segment_change_s = loop.time()
        self._last_segment_count = self._pipeline.segments_promoted

        log.info(
            "watchdog.started",
            max_restarts=self._max_restarts,
            check_interval_s=self._check_interval_s,
            stall_timeout_s=self._stall_timeout_s,
        )

        while not shutdown_event.is_set():
            # Wait for the check interval (interruptible by shutdown)
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=self._check_interval_s,
                )
                # shutdown_event was set — exit cleanly
                break
            except TimeoutError:
                pass  # Normal: check interval elapsed, proceed to health check

            failure_reason = self._detect_failure(loop.time())
            if failure_reason is None:
                continue  # Pipeline is healthy

            # Failure detected — attempt restart
            self._last_failure_reason = failure_reason
            log.warning(
                "watchdog.failure_detected",
                reason=failure_reason,
                restart_count=self._restart_count,
                max_restarts=self._max_restarts,
            )

            if self._restart_count >= self._max_restarts:
                self._giving_up = True
                log.error(
                    "watchdog.giving_up",
                    restart_count=self._restart_count,
                    max_restarts=self._max_restarts,
                    last_failure=failure_reason,
                )
                break

            # Stop the failed pipeline
            self._pipeline.stop()

            # Exponential backoff
            backoff_s = self._base_backoff_s * (2**self._restart_count)
            log.info(
                "watchdog.backoff",
                delay_s=backoff_s,
                attempt=self._restart_count + 1,
            )

            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=backoff_s,
                )
                # Shutdown during backoff — exit cleanly
                break
            except TimeoutError:
                pass  # Backoff elapsed, proceed to restart

            # Attempt restart
            try:
                self._pipeline.start()
                self._restart_count += 1
                # Reset stall detection after successful restart
                self._last_segment_count = self._pipeline.segments_promoted
                self._last_segment_change_s = loop.time()
                log.info(
                    "watchdog.restarted",
                    restart_count=self._restart_count,
                    ffmpeg_pid=self._pipeline.ffmpeg_pid,
                )
            except Exception:
                self._restart_count += 1
                log.exception(
                    "watchdog.restart_failed",
                    restart_count=self._restart_count,
                )

        log.info(
            "watchdog.stopped",
            restart_count=self._restart_count,
            giving_up=self._giving_up,
        )

    # ------------------------------------------------------------------
    # Failure detection
    # ------------------------------------------------------------------

    def _detect_failure(self, now: float) -> str | None:
        """Check pipeline health and return failure reason, or ``None``.

        Args:
            now: Current monotonic time (from ``loop.time()``).

        Returns:
            Human-readable failure reason, or ``None`` if healthy.
        """
        # Check 1: FFmpeg process crashed / exited
        if not self._pipeline.is_active:
            returncode = self._pipeline.returncode
            return f"FFmpeg process exited (returncode={returncode})"

        # Check 2: Segment stall — no new segments promoted
        current_count = self._pipeline.segments_promoted
        if current_count > self._last_segment_count:
            # Progress — reset stall timer
            self._last_segment_count = current_count
            self._last_segment_change_s = now

        elapsed = now - self._last_segment_change_s
        if elapsed > self._stall_timeout_s:
            return f"No new segments for {elapsed:.0f}s (threshold: {self._stall_timeout_s:.0f}s)"

        return None
