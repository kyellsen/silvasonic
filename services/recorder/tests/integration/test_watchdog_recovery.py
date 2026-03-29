"""Integration test: Watchdog auto-recovery with real FFmpeg.

Starts a real FFmpeg process (lavfi mock source), kills it with SIGKILL,
and verifies the Watchdog restarts the pipeline and new segments appear.

Uses a temporary workspace directory — no containers or external services.
"""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import pytest
from silvasonic.recorder.ffmpeg_pipeline import FFmpegConfig, FFmpegPipeline
from silvasonic.recorder.watchdog import RecordingWatchdog
from silvasonic.recorder.workspace import ensure_workspace


@pytest.mark.integration
class TestWatchdogRecovery:
    """Verify watchdog restarts FFmpeg after a crash (real subprocess)."""

    async def test_ffmpeg_crash_recovery(self, tmp_path: Path) -> None:
        """Kill FFmpeg with SIGKILL → watchdog restarts → new segments appear.

        This test uses FFmpeg's built-in ``lavfi`` sine generator as a
        mock audio source — no real hardware needed.
        """
        workspace = tmp_path / "workspace"
        ensure_workspace(workspace)

        config = FFmpegConfig(
            sample_rate=48000,
            channels=1,
            format="S16LE",
            segment_duration_s=1,
            raw_enabled=True,
            processed_enabled=False,  # Single stream for speed
        )

        pipeline = FFmpegPipeline(
            config=config,
            workspace=workspace,
            mock_source=True,
        )

        pipeline.start()
        assert pipeline.is_active

        # Wait for at least 1 segment to be promoted
        for _ in range(30):  # 3s max
            if pipeline.segments_promoted >= 1:
                break
            await asyncio.sleep(0.1)
        assert pipeline.segments_promoted >= 1, "No segments promoted before crash"
        pre_crash_count = pipeline.segments_promoted

        # Kill FFmpeg with SIGKILL (unrecoverable crash)
        ffmpeg_pid = pipeline.ffmpeg_pid
        assert ffmpeg_pid is not None
        import os

        os.kill(ffmpeg_pid, signal.SIGKILL)

        # Wait for FFmpeg to actually die
        for _ in range(20):
            if not pipeline.is_active:
                break
            await asyncio.sleep(0.05)
        assert not pipeline.is_active, "FFmpeg did not die after SIGKILL"

        # Start watchdog — it should detect the crash and restart
        watchdog = RecordingWatchdog(
            pipeline,
            max_restarts=3,
            check_interval_s=0.5,
            stall_timeout_s=30.0,
            base_backoff_s=0.5,
        )

        shutdown = asyncio.Event()

        async def trigger_shutdown() -> None:
            # Poll until recovery is confirmed (max 5s safety ceiling)
            for _ in range(50):
                if watchdog.restart_count >= 1 and pipeline.segments_promoted > pre_crash_count:
                    break
                await asyncio.sleep(0.1)
            shutdown.set()

        task = asyncio.create_task(trigger_shutdown())
        await watchdog.watch(shutdown)
        await task

        # Verify recovery
        assert watchdog.restart_count >= 1, "Watchdog did not restart after crash"
        assert pipeline.is_active, "Pipeline not active after watchdog restart"
        assert pipeline.segments_promoted > pre_crash_count, "No new segments after recovery"
        assert watchdog.last_failure_reason is not None
        assert "FFmpeg process exited" in watchdog.last_failure_reason

        # Cleanup
        pipeline.stop()
