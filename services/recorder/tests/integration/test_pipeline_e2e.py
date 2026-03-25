"""Integration test: Full AudioPipeline lifecycle (hardware-independent).

Exercises the complete pipeline chain with a **mocked** ``sd.InputStream``
that injects synthetic audio into the queue:

    AudioPipeline.start(mock_source=True)
      → MockInputStream generates 440 Hz sine
      → drain_queue() writes to SegmentWriter
      → segment rotation → close_and_promote()
      → WAV files verified in ``tmp_path/data/raw/``

No real audio hardware, no containers, no Redis required.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from silvasonic.recorder.pipeline import AudioPipeline, PipelineConfig
from silvasonic.recorder.workspace import ensure_workspace

pytestmark = [
    pytest.mark.integration,
]


class TestPipelineE2E:
    """Full AudioPipeline lifecycle with MockInputStream → WAV files."""

    @staticmethod
    def _make_pipeline(
        workspace: Path,
        *,
        sample_rate: int = 48000,
        segment_duration_s: int = 1,
        chunk_size: int = 4096,
    ) -> AudioPipeline:
        """Create a mock-source pipeline with short segments."""
        ensure_workspace(workspace)
        cfg = PipelineConfig(
            sample_rate=sample_rate,
            channels=1,
            format="S16LE",
            chunk_size=chunk_size,
            segment_duration_s=segment_duration_s,
            gain_db=0.0,
        )
        return AudioPipeline(
            config=cfg,
            workspace=workspace,
            device="hw:mock,0",
            mock_source=True,
        )

    @staticmethod
    def _run(pipeline: AudioPipeline, duration_s: float) -> None:
        """Run the pipeline drain loop for *duration_s* seconds."""
        pipeline.start()
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            pipeline.drain_queue()
            time.sleep(0.05)
        pipeline.stop()

    def test_produces_wav_files(self, tmp_path: Path) -> None:
        """Pipeline with mock source produces at least 1 WAV in data/raw/."""
        workspace = tmp_path / "e2e_wav"
        pipeline = self._make_pipeline(workspace, segment_duration_s=1)

        # Run for 3s → should produce at least 2 segments (1s each)
        self._run(pipeline, 3.0)

        data_dir = workspace / "data" / "raw"
        wav_files = sorted(data_dir.glob("*.wav"))
        assert len(wav_files) >= 1, f"Expected ≥1 WAV files in {data_dir}, found {len(wav_files)}"

    def test_wav_metadata_correct(self, tmp_path: Path) -> None:
        """WAV files have correct sample rate and channels."""
        workspace = tmp_path / "e2e_meta"
        sr = 48000
        pipeline = self._make_pipeline(workspace, sample_rate=sr, segment_duration_s=1)

        self._run(pipeline, 2.5)

        data_dir = workspace / "data" / "raw"
        wav_files = sorted(data_dir.glob("*.wav"))
        assert len(wav_files) >= 1

        info = sf.info(str(wav_files[0]))
        assert info.samplerate == sr, f"WAV sample rate {info.samplerate} != {sr}"
        assert info.channels == 1
        assert info.frames > 0

    def test_wav_contains_nonzero_data(self, tmp_path: Path) -> None:
        """WAV files contain non-zero audio (synthetic sine wave)."""
        workspace = tmp_path / "e2e_nonzero"
        pipeline = self._make_pipeline(workspace, segment_duration_s=1)

        self._run(pipeline, 2.5)

        data_dir = workspace / "data" / "raw"
        wav_files = sorted(data_dir.glob("*.wav"))
        assert len(wav_files) >= 1

        data, _sr = sf.read(str(wav_files[0]), dtype="int16")
        nonzero = int(np.count_nonzero(data))
        assert nonzero > 0, "WAV should contain non-zero audio data (sine wave)"

    def test_segment_duration_approximately_correct(self, tmp_path: Path) -> None:
        """Each WAV segment is approximately segment_duration_s long."""
        workspace = tmp_path / "e2e_duration"
        seg_s = 2
        pipeline = self._make_pipeline(workspace, segment_duration_s=seg_s)

        # Run long enough for at least 1 full segment + promotion
        self._run(pipeline, seg_s + 1.5)

        data_dir = workspace / "data" / "raw"
        wav_files = sorted(data_dir.glob("*.wav"))
        assert len(wav_files) >= 1

        info = sf.info(str(wav_files[0]))
        actual_s = info.frames / info.samplerate
        # Allow ±50% tolerance (timing imprecision in tests)
        assert actual_s >= seg_s * 0.5, f"Segment too short: {actual_s:.2f}s (expected ~{seg_s}s)"

    def test_buffer_dir_empty_after_stop(self, tmp_path: Path) -> None:
        """After stop(), .buffer/raw/ should be empty (all promoted or discarded)."""
        workspace = tmp_path / "e2e_buffer"
        pipeline = self._make_pipeline(workspace, segment_duration_s=1)

        self._run(pipeline, 2.5)

        buffer_dir = workspace / ".buffer" / "raw"
        remaining = list(buffer_dir.glob("*.wav"))
        assert len(remaining) == 0, (
            f"Buffer should be empty after stop(), found {len(remaining)} files"
        )

    def test_gain_applied_to_wav(self, tmp_path: Path) -> None:
        """Software gain is applied to audio data in the WAV file."""
        workspace_no_gain = tmp_path / "e2e_gain_off"
        workspace_with_gain = tmp_path / "e2e_gain_on"

        # Run without gain
        ensure_workspace(workspace_no_gain)
        cfg_no = PipelineConfig(
            sample_rate=48000,
            channels=1,
            format="S16LE",
            chunk_size=4096,
            segment_duration_s=1,
            gain_db=0.0,
        )
        p_no = AudioPipeline(
            config=cfg_no,
            workspace=workspace_no_gain,
            device="hw:mock,0",
            mock_source=True,
        )
        self._run(p_no, 2.0)

        # Run with +6 dB gain
        ensure_workspace(workspace_with_gain)
        cfg_yes = PipelineConfig(
            sample_rate=48000,
            channels=1,
            format="S16LE",
            chunk_size=4096,
            segment_duration_s=1,
            gain_db=6.0,
        )
        p_yes = AudioPipeline(
            config=cfg_yes,
            workspace=workspace_with_gain,
            device="hw:mock,0",
            mock_source=True,
        )
        self._run(p_yes, 2.0)

        # Compare RMS of first WAV from each
        wavs_no = sorted((workspace_no_gain / "data" / "raw").glob("*.wav"))
        wavs_yes = sorted((workspace_with_gain / "data" / "raw").glob("*.wav"))
        assert len(wavs_no) >= 1 and len(wavs_yes) >= 1

        data_no, _ = sf.read(str(wavs_no[0]), dtype="float64")
        data_yes, _ = sf.read(str(wavs_yes[0]), dtype="float64")

        rms_no = float(np.sqrt(np.mean(data_no**2)))
        rms_yes = float(np.sqrt(np.mean(data_yes**2)))

        # +6 dB ≈ 2x amplitude → RMS should be ~2x higher
        assert rms_yes > rms_no * 1.5, (
            f"Gained audio RMS ({rms_yes:.4f}) should be significantly > ungained ({rms_no:.4f})"
        )
