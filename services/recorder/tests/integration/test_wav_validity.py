"""Integration test: WAV file structural validity.

Ensures that the segments promoted by the FFmpeg pipeline
are actually valid WAV files containing audio frames, not
just empty or corrupted files.

This is a Phase 6 Robustness & Isolation requirement (US-R02).
"""

from __future__ import annotations

import subprocess
import time
import wave
from pathlib import Path

import pytest
from silvasonic.recorder.ffmpeg_pipeline import FFmpegConfig, FFmpegPipeline
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
class TestWavValidity:
    """Verify structural validity of promoted WAV files."""

    def test_promoted_wavs_are_valid(self, tmp_path: Path) -> None:
        """Pipeline produces valid WAV files in both data directories."""
        workspace = tmp_path / "wav_validity"
        ensure_workspace(workspace)

        # 1s segments to get multiple files quickly
        cfg = FFmpegConfig(
            sample_rate=48000,
            channels=1,
            format="S16LE",
            segment_duration_s=1,
            raw_enabled=True,
            processed_enabled=True,
        )
        pipeline = FFmpegPipeline(
            config=cfg,
            workspace=workspace,
            device="hw:mock,0",
            mock_source=True,
        )

        pipeline.start()
        time.sleep(2.5)  # Wait for at least 2 full segments to be promoted
        pipeline.stop()

        # Check raw directory
        raw_wavs = list((workspace / "data" / "raw").glob("*.wav"))
        assert len(raw_wavs) >= 1, "Expected at least 1 raw WAV file"

        for wav_path in raw_wavs:
            # File size sanity check (> 44 bytes header)
            assert wav_path.stat().st_size > 44, f"Raw WAV {wav_path.name} is too small"
            with wave.open(str(wav_path), "rb") as wf:
                assert wf.getnchannels() >= 1
                assert wf.getframerate() > 0
                assert wf.getnframes() > 0, f"Raw WAV {wav_path.name} has 0 frames"

        # Check processed directory
        proc_wavs = list((workspace / "data" / "processed").glob("*.wav"))
        assert len(proc_wavs) >= 1, "Expected at least 1 processed WAV file"

        for wav_path in proc_wavs:
            assert wav_path.stat().st_size > 44, f"Processed WAV {wav_path.name} is too small"
            with wave.open(str(wav_path), "rb") as wf:
                assert wf.getnchannels() >= 1
                assert wf.getframerate() > 0
                assert wf.getnframes() > 0, f"Processed WAV {wav_path.name} has 0 frames"
