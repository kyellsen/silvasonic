"""Unit tests for silvasonic-recorder watchdog (US-R06).

Tests the RecordingWatchdog class including:
- Pure logic: _detect_failure (crashes, stalls using explicit time)
- Loop behavior: watch() (restarts, backoffs, max restarts, shutdown)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from silvasonic.recorder.watchdog import RecordingWatchdog


def _make_pipeline(
    *,
    is_active: bool = True,
    segments_promoted: int = 0,
    returncode: int | None = None,
) -> MagicMock:
    """Create a mock FFmpegPipeline with configurable properties."""
    pipeline = MagicMock()
    type(pipeline).is_active = PropertyMock(return_value=is_active)
    type(pipeline).segments_promoted = PropertyMock(return_value=segments_promoted)
    type(pipeline).returncode = PropertyMock(return_value=returncode)
    type(pipeline).ffmpeg_pid = PropertyMock(return_value=12345)
    return pipeline


# ===========================================================================
# Pure Logic Tests: _detect_failure
# ===========================================================================


@pytest.mark.unit
class TestWatchdogDetectFailure:
    """Explicit tests for _detect_failure logic using controlled time basis."""

    def test_healthy(self) -> None:
        """No failure detected when active and within stall timeout."""
        pipeline = _make_pipeline(is_active=True, segments_promoted=5)
        watchdog = RecordingWatchdog(pipeline, stall_timeout_s=30.0)
        watchdog._last_segment_count = 5
        watchdog._last_segment_change_s = 100.0

        assert watchdog._detect_failure(110.0) is None

    def test_crash(self) -> None:
        """Crash detected immediately when pipeline is not active."""
        pipeline = _make_pipeline(is_active=False, returncode=-9)
        watchdog = RecordingWatchdog(pipeline)

        reason = watchdog._detect_failure(100.0)
        assert reason is not None
        assert "exited" in reason
        assert "-9" in reason

    def test_stall(self) -> None:
        """Stall detected when segments don't increase past timeout."""
        pipeline = _make_pipeline(is_active=True, segments_promoted=5)
        watchdog = RecordingWatchdog(pipeline, stall_timeout_s=30.0)
        watchdog._last_segment_count = 5
        watchdog._last_segment_change_s = 100.0

        # Exactly at timeout -> OK
        assert watchdog._detect_failure(130.0) is None
        # Past timeout -> Stalled
        reason = watchdog._detect_failure(131.0)
        assert reason is not None
        assert "No new segments" in reason

    def test_progress_resets_stall(self) -> None:
        """Stall timer resets globally when segments increase."""
        pipeline = _make_pipeline(is_active=True, segments_promoted=6)  # Increased!
        watchdog = RecordingWatchdog(pipeline, stall_timeout_s=30.0)
        watchdog._last_segment_count = 5
        watchdog._last_segment_change_s = 100.0

        # Event at time 140 (past previous timeout), but segments increased
        assert watchdog._detect_failure(140.0) is None
        # State should be updated
        assert watchdog._last_segment_count == 6
        assert watchdog._last_segment_change_s == 140.0


# ===========================================================================
# Loop Behavior Tests: watch()
# ===========================================================================


@pytest.mark.unit
class TestWatchdogHealthy:
    """Watchdog does nothing when the pipeline is healthy."""

    async def test_no_restart_when_pipeline_healthy(self) -> None:
        """Watchdog exits cleanly via shutdown_event without restarting."""
        pipeline = _make_pipeline(segments_promoted=5)
        watchdog = RecordingWatchdog(pipeline, max_restarts=5)

        shutdown = asyncio.Event()

        # Shutdown immediately on the first check logic block
        def mock_is_active() -> bool:
            shutdown.set()
            return True

        type(pipeline).is_active = PropertyMock(side_effect=mock_is_active)

        await watchdog.watch(shutdown)

        assert watchdog.restart_count == 0
        assert watchdog.is_giving_up is False
        assert watchdog.last_failure_reason is None
        pipeline.stop.assert_not_called()
        pipeline.start.assert_not_called()


@pytest.mark.unit
class TestWatchdogInitialState:
    """Watchdog properties are correct before watch() is called."""

    def test_initial_properties(self) -> None:
        """All properties have expected defaults before monitoring starts."""
        pipeline = _make_pipeline(is_active=True)
        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=3,
            check_interval_s=1.0,
            stall_timeout_s=30.0,
            base_backoff_s=2.0,
        )

        assert watchdog.restart_count == 0
        assert watchdog.max_restarts == 3
        assert watchdog.is_giving_up is False
        assert watchdog.last_failure_reason is None


@pytest.mark.unit
class TestWatchdogCrashReaction:
    """Watchdog executes restart routine upon crash detection."""

    async def test_executes_restart_and_resumes(self) -> None:
        """Mock is_active=False -> watchdog stops, starts, then resumes."""
        pipeline = _make_pipeline(is_active=False, returncode=-9)
        watchdog = RecordingWatchdog(
            pipeline, max_restarts=5, check_interval_s=0.01, base_backoff_s=0.01
        )
        shutdown = asyncio.Event()

        # Ensure delay doesn't drag out the test unnecessarily
        with patch("silvasonic.recorder.watchdog.asyncio.sleep", new_callable=AsyncMock):

            def on_start() -> None:
                # Once restarted, pipeline becomes healthy and we set shutdown
                type(pipeline).is_active = PropertyMock(return_value=True)
                shutdown.set()

            pipeline.start.side_effect = on_start

            await watchdog.watch(shutdown)

            assert watchdog.restart_count == 1
            assert watchdog.last_failure_reason is not None
            assert "exited" in watchdog.last_failure_reason
            pipeline.stop.assert_called_once()
            pipeline.start.assert_called_once()


@pytest.mark.unit
class TestWatchdogBackoff:
    """Watchdog applies exponential backoff delays using loop.time()."""

    async def test_exhausts_retries_with_backoff(self) -> None:
        """Pipeline stays crashed -> exhausts retries -> sets is_giving_up."""
        pipeline = _make_pipeline(is_active=False, returncode=1)
        # Stays crashed
        pipeline.start.side_effect = lambda: None

        watchdog = RecordingWatchdog(
            pipeline, max_restarts=3, check_interval_s=0.01, base_backoff_s=0.01
        )
        shutdown = asyncio.Event()

        # check_interval and backoff are set to 0.01 so it inherently executes fast
        with pytest.raises(RuntimeError, match="Watchdog exhausted all 3 restart attempts"):
            await watchdog.watch(shutdown)

        assert watchdog.restart_count == 3
        assert watchdog.is_giving_up is True


@pytest.mark.unit
class TestWatchdogShutdownDuringBackoff:
    """Watchdog respects shutdown even when in the backoff sleep."""

    async def test_respects_shutdown_during_backoff(self) -> None:
        """Setting shutdown_event exits backoff loop early."""
        pipeline = _make_pipeline(is_active=False, returncode=1)

        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=5,
            check_interval_s=0.01,
            base_backoff_s=10.0,  # Massive delay, would hang if wait_for wasn't interrupted
        )
        shutdown = asyncio.Event()

        def stop_side_effect() -> None:
            # Set the shutdown event "soon" so it triggers during the backoff's wait_for
            asyncio.get_running_loop().call_soon(shutdown.set)

        pipeline.stop.side_effect = stop_side_effect

        await watchdog.watch(shutdown)

        # Detected failure, entered backoff, shutdown event
        # set immediately by side_effect, exited gracefully
        assert watchdog.restart_count == 0
        assert watchdog.is_giving_up is False


@pytest.mark.unit
class TestWatchdogStartFailure:
    """Watchdog handles pipeline start() exceptions."""

    async def test_start_exception_counts_as_restart(self) -> None:
        """If start() raises, the attempt counts toward max_restarts."""
        pipeline = _make_pipeline(is_active=False, returncode=1)
        pipeline.start.side_effect = RuntimeError("No audio device")

        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=2,
            check_interval_s=0.01,
            base_backoff_s=0.01,
        )

        shutdown = asyncio.Event()

        with (
            patch("silvasonic.recorder.watchdog.log"),
            pytest.raises(RuntimeError, match="Watchdog exhausted all 2 restart attempts"),
        ):
            await watchdog.watch(shutdown)

        assert watchdog.restart_count == 2
        assert watchdog.is_giving_up is True
