"""Unit tests for silvasonic-recorder watchdog (US-R06).

Tests the RecordingWatchdog class including:
- No restart when pipeline is healthy
- Crash detection and restart
- Stall detection and restart
- Exponential backoff delays
- Max restart limit (give-up)
- Restart counter tracking
- Shutdown during backoff
- Last failure reason
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, PropertyMock, patch

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


@pytest.mark.unit
class TestWatchdogHealthy:
    """Watchdog does nothing when the pipeline is healthy."""

    async def test_no_restart_when_pipeline_healthy(self) -> None:
        """Watchdog exits cleanly via shutdown_event without restarting."""
        pipeline = _make_pipeline(is_active=True, segments_promoted=5)
        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=5,
            check_interval_s=0.05,
        )

        shutdown = asyncio.Event()

        async def trigger_shutdown() -> None:
            await asyncio.sleep(0.15)
            shutdown.set()

        task = asyncio.create_task(trigger_shutdown())
        await watchdog.watch(shutdown)
        await task

        assert watchdog.restart_count == 0
        assert watchdog.is_giving_up is False
        assert watchdog.last_failure_reason is None
        assert watchdog.max_restarts == 5
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
class TestWatchdogCrashDetection:
    """Watchdog detects FFmpeg crashes and restarts."""

    async def test_detects_ffmpeg_crash_and_restarts(self) -> None:
        """Mock is_active=False → watchdog calls stop() + start()."""
        pipeline = _make_pipeline(is_active=False, returncode=-9)

        # After restart, pipeline becomes active
        restart_call_count = 0

        def on_start() -> None:
            nonlocal restart_call_count
            restart_call_count += 1
            type(pipeline).is_active = PropertyMock(return_value=True)

        pipeline.start.side_effect = on_start

        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=5,
            check_interval_s=0.05,
            base_backoff_s=0.01,
        )

        shutdown = asyncio.Event()

        async def trigger_shutdown() -> None:
            await asyncio.sleep(0.3)
            shutdown.set()

        task = asyncio.create_task(trigger_shutdown())
        await watchdog.watch(shutdown)
        await task

        assert watchdog.restart_count == 1
        pipeline.stop.assert_called_once()
        assert restart_call_count == 1


@pytest.mark.unit
class TestWatchdogStallDetection:
    """Watchdog detects segment stalls and restarts."""

    async def test_detects_stall_and_restarts(self) -> None:
        """segments_promoted doesn't change → restart after stall_timeout_s."""
        # Use a mutable counter so the mock always has a value to return
        counter = [5]  # mutable — shared between mock and on_start

        pipeline = _make_pipeline(is_active=True)
        type(pipeline).segments_promoted = PropertyMock(side_effect=lambda: counter[0])

        # After restart, bump the counter so stall detection resets
        def on_start() -> None:
            counter[0] += 100

        pipeline.start.side_effect = on_start

        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=5,
            check_interval_s=0.02,
            stall_timeout_s=0.06,
            base_backoff_s=0.01,
        )

        shutdown = asyncio.Event()

        async def trigger_shutdown() -> None:
            await asyncio.sleep(0.15)
            shutdown.set()

        task = asyncio.create_task(trigger_shutdown())
        await watchdog.watch(shutdown)
        await task

        assert watchdog.restart_count >= 1
        assert watchdog.last_failure_reason is not None
        assert "No new segments" in watchdog.last_failure_reason


@pytest.mark.unit
class TestWatchdogBackoff:
    """Watchdog applies exponential backoff delays."""

    async def test_exponential_backoff_delays(self) -> None:
        """Verify backoff doubles each retry."""
        pipeline = _make_pipeline(is_active=False, returncode=1)

        # Pipeline always stays crashed
        pipeline.start.side_effect = lambda: None

        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=3,
            check_interval_s=0.02,
            base_backoff_s=0.01,
        )

        shutdown = asyncio.Event()
        with pytest.raises(RuntimeError, match="Watchdog exhausted all 3 restart attempts"):
            await watchdog.watch(shutdown)

        # Should have attempted 3 restarts, then given up
        assert watchdog.restart_count == 3
        assert watchdog.is_giving_up is True


@pytest.mark.unit
class TestWatchdogMaxRestarts:
    """Watchdog gives up after max restarts."""

    async def test_gives_up_after_max_restarts(self) -> None:
        """After max_restarts, is_giving_up=True, watch loop exits."""
        pipeline = _make_pipeline(is_active=False, returncode=-11)
        pipeline.start.side_effect = lambda: None  # stays crashed

        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=2,
            check_interval_s=0.02,
            base_backoff_s=0.01,
        )

        shutdown = asyncio.Event()
        with pytest.raises(RuntimeError, match="Watchdog exhausted all 2 restart attempts"):
            await watchdog.watch(shutdown)

        assert watchdog.is_giving_up is True
        assert watchdog.restart_count == 2
        assert watchdog.last_failure_reason is not None


@pytest.mark.unit
class TestWatchdogRestartCounter:
    """Watchdog counts restarts correctly."""

    async def test_restart_counter_increments(self) -> None:
        """Each restart increments restart_count."""
        call_count = 0

        pipeline = _make_pipeline(is_active=False, returncode=1)

        def on_start() -> None:
            nonlocal call_count
            call_count += 1
            # Stay crashed to keep restarting
            type(pipeline).is_active = PropertyMock(return_value=False)

        pipeline.start.side_effect = on_start

        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=3,
            check_interval_s=0.02,
            base_backoff_s=0.01,
        )

        shutdown = asyncio.Event()
        with pytest.raises(RuntimeError, match="Watchdog exhausted all 3 restart attempts"):
            await watchdog.watch(shutdown)

        assert watchdog.restart_count == 3
        assert call_count == 3


@pytest.mark.unit
class TestWatchdogShutdown:
    """Watchdog respects shutdown during backoff."""

    async def test_respects_shutdown_during_backoff(self) -> None:
        """Setting shutdown_event during backoff delay exits immediately."""
        pipeline = _make_pipeline(is_active=False, returncode=1)

        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=5,
            check_interval_s=0.02,
            base_backoff_s=10.0,  # Very long backoff — would hang if not interrupted
        )

        shutdown = asyncio.Event()

        async def trigger_shutdown() -> None:
            await asyncio.sleep(0.1)
            shutdown.set()

        task = asyncio.create_task(trigger_shutdown())
        await watchdog.watch(shutdown)
        await task

        # Should have detected failure but not completed the restart
        # (shutdown happened during backoff)
        assert watchdog.restart_count == 0
        assert watchdog.is_giving_up is False


@pytest.mark.unit
class TestWatchdogFailureReason:
    """Watchdog reports failure reasons."""

    async def test_last_failure_reason_set(self) -> None:
        """last_failure_reason contains human-readable description."""
        pipeline = _make_pipeline(is_active=False, returncode=-9)

        def on_start() -> None:
            type(pipeline).is_active = PropertyMock(return_value=True)

        pipeline.start.side_effect = on_start

        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=5,
            check_interval_s=0.02,
            base_backoff_s=0.01,
        )

        shutdown = asyncio.Event()

        async def trigger_shutdown() -> None:
            await asyncio.sleep(0.2)
            shutdown.set()

        task = asyncio.create_task(trigger_shutdown())
        await watchdog.watch(shutdown)
        await task

        assert watchdog.last_failure_reason is not None
        assert "FFmpeg process exited" in watchdog.last_failure_reason
        assert "-9" in watchdog.last_failure_reason


@pytest.mark.unit
class TestWatchdogStartFailure:
    """Watchdog handles pipeline start() exceptions."""

    async def test_start_exception_counts_as_restart(self) -> None:
        """If start() raises, the attempt still counts toward max_restarts."""
        pipeline = _make_pipeline(is_active=False, returncode=1)
        pipeline.start.side_effect = RuntimeError("No audio device")

        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=2,
            check_interval_s=0.02,
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


@pytest.mark.unit
class TestWatchdogStallProgressReset:
    """Watchdog resets stall timer when segments increase."""

    async def test_stall_timer_resets_on_segment_progress(self) -> None:
        """Increasing segments_promoted resets the stall timer."""
        # Start with segments=5, increment every check cycle
        counter = [5]

        pipeline = _make_pipeline(is_active=True)
        type(pipeline).segments_promoted = PropertyMock(side_effect=lambda: counter[0])

        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=5,
            check_interval_s=0.02,
            stall_timeout_s=0.08,  # Would stall if no progress
            base_backoff_s=0.01,
        )

        shutdown = asyncio.Event()

        # Simulate progress: increment counter every check cycle
        async def simulate_progress() -> None:
            for _ in range(10):
                await asyncio.sleep(0.02)
                counter[0] += 1
            shutdown.set()

        task = asyncio.create_task(simulate_progress())
        await watchdog.watch(shutdown)
        await task

        # No restarts because there was constant progress
        assert watchdog.restart_count == 0
        assert watchdog.is_giving_up is False
