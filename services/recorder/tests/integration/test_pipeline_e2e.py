"""Integration test: Full FFmpegPipeline lifecycle (hardware-independent).

Exercises the complete dual-stream pipeline with FFmpeg's built-in
``lavfi`` signal generator (ADR-0024):

    FFmpegPipeline.start(mock_source=True)
      → FFmpeg generates 440 Hz sine via lavfi
      → segment muxer writes .buffer/raw/ and .buffer/processed/
      → SegmentPromoter promotes to data/raw/ and data/processed/
      → segment rotation via -segment_time

No real audio hardware, no containers, no Redis required.
Requires FFmpeg to be installed on the test runner.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from silvasonic.recorder.ffmpeg_pipeline import (
    FFmpegConfig,
    FFmpegPipeline,
)
from silvasonic.recorder.workspace import ensure_workspace

pytestmark = [
    pytest.mark.integration,
]


def _ffmpeg_available() -> bool:
    """Check if FFmpeg is available on the system."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


skip_no_ffmpeg = pytest.mark.skipif(
    not _ffmpeg_available(),
    reason="FFmpeg not installed — skip integration tests",
)


@skip_no_ffmpeg
class TestFFmpegPipelineE2E:
    """Full FFmpegPipeline lifecycle with lavfi → WAV files."""

    # ── Test timing constants (DRY) ──────────────────────────────────────
    _SEGMENT_S = 1  # Shortest allowed segment (PositiveInt ≥ 1)
    _RUN_S = 1.2  # Enough for 1 full rotation + margin
    _RUN_LONG_S = 2.5  # For count-assertions (≥2 rotations needed)

    @staticmethod
    def _make_pipeline(
        workspace: Path,
        *,
        sample_rate: int = 48000,
        segment_duration_s: int = 2,
        raw_enabled: bool = True,
        processed_enabled: bool = True,
        gain_db: float = 0.0,
    ) -> FFmpegPipeline:
        """Create a mock-source pipeline with short segments."""
        ensure_workspace(workspace)
        cfg = FFmpegConfig(
            sample_rate=sample_rate,
            channels=1,
            format="S16LE",
            segment_duration_s=segment_duration_s,
            gain_db=gain_db,
            raw_enabled=raw_enabled,
            processed_enabled=processed_enabled,
        )
        return FFmpegPipeline(
            config=cfg,
            workspace=workspace,
            device="hw:mock,0",  # Ignored when mock_source=True
            mock_source=True,
        )

    @staticmethod
    def _run(pipeline: FFmpegPipeline, duration_s: float) -> None:
        """Run the pipeline for *duration_s* seconds, then stop."""
        pipeline.start()
        time.sleep(duration_s)
        pipeline.stop()

    def test_produces_wav_files(self, tmp_path: Path) -> None:
        """Pipeline with mock source produces at least 1 WAV in data/raw/."""
        workspace = tmp_path / "e2e_wav"
        pipeline = self._make_pipeline(workspace, segment_duration_s=self._SEGMENT_S)

        self._run(pipeline, self._RUN_S)

        data_dir = workspace / "data" / "raw"
        wav_files = sorted(data_dir.glob("*.wav"))
        assert len(wav_files) >= 1, f"Expected ≥1 WAV files in {data_dir}, found {len(wav_files)}"

    def test_dual_stream_produces_both_dirs(self, tmp_path: Path) -> None:
        """Pipeline produces WAV files in both data/raw/ and data/processed/."""
        workspace = tmp_path / "e2e_dual"
        pipeline = self._make_pipeline(workspace, segment_duration_s=self._SEGMENT_S)

        self._run(pipeline, self._RUN_S)

        raw_wavs = sorted((workspace / "data" / "raw").glob("*.wav"))
        proc_wavs = sorted((workspace / "data" / "processed").glob("*.wav"))
        assert len(raw_wavs) >= 1, f"Expected ≥1 raw WAVs, got {len(raw_wavs)}"
        assert len(proc_wavs) >= 1, f"Expected ≥1 processed WAVs, got {len(proc_wavs)}"

    def test_buffer_dirs_empty_after_stop(self, tmp_path: Path) -> None:
        """After stop(), buffer dirs have at most 1 file (in-progress at SIGINT)."""
        workspace = tmp_path / "e2e_buffer"
        pipeline = self._make_pipeline(workspace, segment_duration_s=self._SEGMENT_S)

        self._run(pipeline, self._RUN_S)

        for stream in ("raw", "processed"):
            buf = workspace / ".buffer" / stream
            remaining = list(buf.glob("*.wav"))
            # At most 1 file may remain: the segment being written when SIGINT arrived.
            # Completed segments are promoted, only the in-progress one stays.
            assert len(remaining) <= 1, (
                f"Buffer .buffer/{stream}/ should have ≤1 file, found {len(remaining)}"
            )

    def test_raw_only_mode(self, tmp_path: Path) -> None:
        """processed_enabled=False → only data/raw/ has WAV files."""
        workspace = tmp_path / "e2e_raw_only"
        pipeline = self._make_pipeline(
            workspace,
            segment_duration_s=self._SEGMENT_S,
            raw_enabled=True,
            processed_enabled=False,
        )

        self._run(pipeline, self._RUN_S)

        raw_wavs = list((workspace / "data" / "raw").glob("*.wav"))
        proc_wavs = list((workspace / "data" / "processed").glob("*.wav"))
        assert len(raw_wavs) >= 1
        assert len(proc_wavs) == 0, f"No processed WAVs expected, got {len(proc_wavs)}"

    def test_processed_only_mode(self, tmp_path: Path) -> None:
        """raw_enabled=False → only data/processed/ has WAV files."""
        workspace = tmp_path / "e2e_proc_only"
        pipeline = self._make_pipeline(
            workspace,
            segment_duration_s=self._SEGMENT_S,
            raw_enabled=False,
            processed_enabled=True,
        )

        self._run(pipeline, self._RUN_S)

        raw_wavs = list((workspace / "data" / "raw").glob("*.wav"))
        proc_wavs = list((workspace / "data" / "processed").glob("*.wav"))
        assert len(proc_wavs) >= 1
        assert len(raw_wavs) == 0, f"No raw WAVs expected, got {len(raw_wavs)}"

    def test_segments_promoted_count(self, tmp_path: Path) -> None:
        """Pipeline reports correct segment promotion count."""
        workspace = tmp_path / "e2e_count"
        pipeline = self._make_pipeline(workspace, segment_duration_s=self._SEGMENT_S)

        self._run(pipeline, self._RUN_LONG_S)

        assert pipeline.segments_promoted >= 2, (
            f"Expected ≥2 promoted segments, got {pipeline.segments_promoted}"
        )

    def test_pipeline_lifecycle(self, tmp_path: Path) -> None:
        """Pipeline starts, records, and stops cleanly."""
        workspace = tmp_path / "e2e_lifecycle"
        pipeline = self._make_pipeline(workspace, segment_duration_s=self._SEGMENT_S)

        # Not started
        assert not pipeline.is_active
        assert pipeline.ffmpeg_pid is None

        # Start
        pipeline.start()
        assert pipeline.is_active
        assert pipeline.ffmpeg_pid is not None

        time.sleep(1.5)

        # Stop
        pipeline.stop()
        assert not pipeline.is_active
        assert pipeline.ffmpeg_pid is None  # Cleared after stop
