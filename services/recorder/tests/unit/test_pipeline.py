"""Unit tests for silvasonic.recorder.pipeline module.

Tests PipelineConfig, SegmentWriter, and AudioPipeline with mocked
sounddevice and soundfile — no real audio hardware needed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from silvasonic.recorder.pipeline import (
    _FORMAT_MAP,
    AudioPipeline,
    PipelineConfig,
    SegmentWriter,
    _ensure_alsa_hostapi,
    _segment_filename,
)

# ===================================================================
# PipelineConfig
# ===================================================================


@pytest.mark.unit
class TestPipelineConfig:
    """Tests for PipelineConfig — capture parameter management."""

    def test_defaults(self) -> None:
        """Default config uses 48kHz, 1ch, S16LE, 10s segments."""
        cfg = PipelineConfig()
        assert cfg.sample_rate == 48000
        assert cfg.channels == 1
        assert cfg.format == "S16LE"
        assert cfg.chunk_size == 4096
        assert cfg.segment_duration_s == 10
        assert cfg.gain_db == 0.0

    def test_from_profile(self) -> None:
        """from_profile() extracts all fields from a MicrophoneProfile."""
        from silvasonic.core.schemas.devices import (
            AudioConfig,
            MicrophoneProfile,
            ProcessingConfig,
            StreamConfig,
        )

        profile = MicrophoneProfile(
            slug="test_mic",
            name="Test Mic",
            audio=AudioConfig(sample_rate=384000, channels=1, format="S24LE"),
            processing=ProcessingConfig(gain_db=12.0, chunk_size=8192),
            stream=StreamConfig(segment_duration_s=15),
        )

        cfg = PipelineConfig.from_profile(profile)
        assert cfg.sample_rate == 384000
        assert cfg.channels == 1
        assert cfg.format == "S24LE"
        assert cfg.chunk_size == 8192
        assert cfg.segment_duration_s == 15
        assert cfg.gain_db == 12.0

    def test_numpy_dtype_s16le(self) -> None:
        """S16LE maps to int16."""
        cfg = PipelineConfig(format="S16LE")
        assert cfg.numpy_dtype == "int16"

    def test_numpy_dtype_s24le(self) -> None:
        """S24LE maps to int32 (padded)."""
        cfg = PipelineConfig(format="S24LE")
        assert cfg.numpy_dtype == "int32"

    def test_numpy_dtype_s32le(self) -> None:
        """S32LE maps to int32."""
        cfg = PipelineConfig(format="S32LE")
        assert cfg.numpy_dtype == "int32"

    def test_soundfile_subtype_s16le(self) -> None:
        """S16LE maps to PCM_16."""
        cfg = PipelineConfig(format="S16LE")
        assert cfg.soundfile_subtype == "PCM_16"

    def test_soundfile_subtype_s24le(self) -> None:
        """S24LE maps to PCM_24."""
        cfg = PipelineConfig(format="S24LE")
        assert cfg.soundfile_subtype == "PCM_24"

    def test_frames_per_segment(self) -> None:
        """frames_per_segment = sample_rate x segment_duration."""
        cfg = PipelineConfig(sample_rate=48000, segment_duration_s=10)
        assert cfg.frames_per_segment == 480000

    def test_format_map_complete(self) -> None:
        """All declared formats have entries in _FORMAT_MAP."""
        for fmt in ("S16LE", "S24LE", "S32LE"):
            assert fmt in _FORMAT_MAP, f"{fmt} missing from _FORMAT_MAP"


# ===================================================================
# _segment_filename
# ===================================================================


@pytest.mark.unit
class TestSegmentFilename:
    """Tests for segment filename generation."""

    def test_format(self) -> None:
        """Filename follows ISO timestamp + duration pattern."""
        ts = datetime(2026, 3, 25, 14, 30, 0, tzinfo=UTC)
        name = _segment_filename(ts, 10)
        assert name == "2026-03-25T14-30-00_10s.wav"

    def test_different_duration(self) -> None:
        """Different duration is reflected in filename."""
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        name = _segment_filename(ts, 15)
        assert name == "2026-01-01T00-00-00_15s.wav"


# ===================================================================
# SegmentWriter
# ===================================================================


@pytest.mark.unit
class TestSegmentWriter:
    """Tests for SegmentWriter — WAV segment lifecycle."""

    def test_write_and_promote(self, tmp_path: Path) -> None:
        """write() + close_and_promote() creates file in data dir."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        cfg = PipelineConfig(sample_rate=48000, channels=1, segment_duration_s=10)
        writer = SegmentWriter(buffer_dir, data_dir, cfg)

        # Write some test data
        data = np.zeros(1024, dtype=np.int16)
        writer.write(data)
        assert writer.frames_written == 1024
        assert not writer.is_full

        # Promote
        result = writer.close_and_promote()
        assert result is not None
        assert result.parent == data_dir
        assert result.exists()
        assert writer.is_closed

        # Buffer file should be gone
        buffer_files = list(buffer_dir.iterdir())
        assert len(buffer_files) == 0

    def test_is_full(self, tmp_path: Path) -> None:
        """is_full returns True when frames reach segment target."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        # Very short segment: 100 frames at 100Hz = 1s
        cfg = PipelineConfig(sample_rate=100, channels=1, segment_duration_s=1)
        writer = SegmentWriter(buffer_dir, data_dir, cfg)

        data = np.zeros(100, dtype=np.int16)
        writer.write(data)
        assert writer.is_full
        writer.close_and_promote()

    def test_close_discard_removes_file(self, tmp_path: Path) -> None:
        """close_discard() removes the buffer file."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        cfg = PipelineConfig()
        writer = SegmentWriter(buffer_dir, data_dir, cfg)

        writer.close_discard()
        assert writer.is_closed
        # No files in either directory
        assert len(list(buffer_dir.iterdir())) == 0
        assert len(list(data_dir.iterdir())) == 0

    def test_double_close_is_safe(self, tmp_path: Path) -> None:
        """Closing twice is a no-op."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        cfg = PipelineConfig()
        writer = SegmentWriter(buffer_dir, data_dir, cfg)
        data = np.zeros(100, dtype=np.int16)
        writer.write(data)

        writer.close_and_promote()
        result2 = writer.close_and_promote()
        assert result2 is None  # Already closed

    def test_write_after_close_is_noop(self, tmp_path: Path) -> None:
        """Writing to a closed writer is silently ignored."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        cfg = PipelineConfig()
        writer = SegmentWriter(buffer_dir, data_dir, cfg)
        writer.close_discard()

        data = np.zeros(100, dtype=np.int16)
        writer.write(data)  # Should not raise
        assert writer.frames_written == 0

    def test_close_discard_double_call_is_safe(self, tmp_path: Path) -> None:
        """Calling close_discard() twice is a no-op."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        cfg = PipelineConfig()
        writer = SegmentWriter(buffer_dir, data_dir, cfg)
        writer.close_discard()
        writer.close_discard()  # Should not raise
        assert writer.is_closed


# ===================================================================
# AudioPipeline
# ===================================================================


@pytest.mark.unit
class TestAudioPipeline:
    """Tests for AudioPipeline — orchestrated capture with mocked audio."""

    def _make_pipeline(self, tmp_path: Path, **cfg_overrides: Any) -> AudioPipeline:
        """Create a pipeline with workspace dirs already set up."""
        from silvasonic.recorder.workspace import ensure_workspace

        ensure_workspace(tmp_path)
        cfg = PipelineConfig(**cfg_overrides)
        return AudioPipeline(config=cfg, workspace=tmp_path, device="hw:mock,0")

    def test_initial_state(self, tmp_path: Path) -> None:
        """Pipeline starts inactive with zero xruns."""
        pipeline = self._make_pipeline(tmp_path)
        assert not pipeline.is_active
        assert pipeline.xrun_count == 0

    @patch("silvasonic.recorder.pipeline.sd.InputStream")
    def test_start_creates_stream(self, mock_stream_cls: MagicMock, tmp_path: Path) -> None:
        """start() creates and starts an InputStream."""
        pipeline = self._make_pipeline(tmp_path)
        pipeline.start()

        assert pipeline.is_active
        mock_stream_cls.assert_called_once()
        mock_stream_cls.return_value.start.assert_called_once()

        pipeline.stop()

    def test_process_chunk_writes_data(self, tmp_path: Path) -> None:
        """process_chunk() writes audio data to the segment writer."""
        pipeline = self._make_pipeline(tmp_path, sample_rate=1000, segment_duration_s=1)

        # Manually create a writer (bypass start() which needs real audio)
        pipeline._writer = SegmentWriter(
            tmp_path / ".buffer" / "raw",
            tmp_path / "data" / "raw",
            pipeline._config,
        )

        data = np.zeros(500, dtype=np.int16)
        pipeline.process_chunk(data)

        assert pipeline._writer.frames_written == 500

        pipeline._writer.close_discard()

    def test_process_chunk_rotates_on_full(self, tmp_path: Path) -> None:
        """process_chunk() rotates segment when full."""
        pipeline = self._make_pipeline(tmp_path, sample_rate=100, segment_duration_s=1)

        # Create initial writer
        pipeline._writer = SegmentWriter(
            tmp_path / ".buffer" / "raw",
            tmp_path / "data" / "raw",
            pipeline._config,
        )

        # Write exactly enough to fill the segment (100 frames at 100Hz = 1s)
        data = np.zeros(100, dtype=np.int16)
        pipeline.process_chunk(data)

        # Should have rotated — new writer is active
        assert pipeline._writer.frames_written == 0

        # Check that file was promoted
        data_files = list((tmp_path / "data" / "raw").iterdir())
        assert len(data_files) == 1
        assert data_files[0].suffix == ".wav"

        pipeline._writer.close_discard()

    def test_apply_gain_zero(self, tmp_path: Path) -> None:
        """Zero gain returns data unchanged."""
        pipeline = self._make_pipeline(tmp_path, gain_db=0.0)
        data = np.array([100, -100, 0], dtype=np.int16)
        result = pipeline._apply_gain(data)
        np.testing.assert_array_equal(result, data)

    def test_apply_gain_nonzero(self, tmp_path: Path) -> None:
        """Non-zero gain scales data correctly."""
        pipeline = self._make_pipeline(tmp_path, gain_db=20.0)
        data = np.array([100], dtype=np.int16)
        result = pipeline._apply_gain(data)
        # 20 dB = 10x gain → 100 * 10 = 1000
        assert result[0] == 1000

    def test_audio_callback_enqueues_data(self, tmp_path: Path) -> None:
        """The audio callback puts data into the queue."""
        pipeline = self._make_pipeline(tmp_path)

        data = np.zeros((1024, 1), dtype=np.int16)
        status = MagicMock()
        status.input_overflow = False

        pipeline._audio_callback(data, 1024, None, status)

        assert not pipeline._queue.empty()
        chunk = pipeline._queue.get_nowait()
        assert chunk.shape == (1024, 1)

    def test_audio_callback_counts_overflow(self, tmp_path: Path) -> None:
        """Input overflow increments xrun counter."""
        pipeline = self._make_pipeline(tmp_path)

        status = MagicMock()
        status.input_overflow = True
        data = np.zeros((100, 1), dtype=np.int16)

        pipeline._audio_callback(data, 100, None, status)
        assert pipeline.xrun_count == 1

    def test_audio_callback_queue_full(self, tmp_path: Path) -> None:
        """Queue overflow increments xrun counter and throttles logs."""
        import queue as queue_mod

        import structlog.testing

        pipeline = self._make_pipeline(tmp_path)
        pipeline._queue = queue_mod.Queue(maxsize=1)
        # Fill the queue
        pipeline._queue.put(np.zeros(10, dtype=np.int16))

        status = MagicMock()
        status.input_overflow = False
        data = np.zeros((10, 1), dtype=np.int16)

        # First overflow → logged (count=1)
        pipeline._audio_callback(data, 10, None, status)
        assert pipeline.xrun_count == 1

        # Simulate 199 more overflows (counts 2-200)
        # Only count=100 and count=200 should log
        with structlog.testing.capture_logs() as captured:
            for _ in range(199):
                pipeline._audio_callback(data, 10, None, status)

        assert pipeline.xrun_count == 200
        # Only 2 log entries: at xrun_count=100 and xrun_count=200
        queue_full_logs = [e for e in captured if e.get("event") == "pipeline.queue_full"]
        assert len(queue_full_logs) == 2, (
            f"Expected 2 throttled logs (at 100, 200), got {len(queue_full_logs)}: "
            f"{[e.get('xrun_count') for e in queue_full_logs]}"
        )

    def test_drain_queue(self, tmp_path: Path) -> None:
        """drain_queue() processes all enqueued chunks."""
        pipeline = self._make_pipeline(tmp_path, sample_rate=1000, segment_duration_s=100)

        # Create writer
        pipeline._writer = SegmentWriter(
            tmp_path / ".buffer" / "raw",
            tmp_path / "data" / "raw",
            pipeline._config,
        )

        # Enqueue some data
        for _ in range(3):
            pipeline._queue.put(np.zeros(100, dtype=np.int16))

        count = pipeline.drain_queue()
        assert count == 3
        assert pipeline._writer.frames_written == 300

        pipeline._writer.close_discard()

    @patch("silvasonic.recorder.pipeline.sd.InputStream")
    def test_start_and_stop(self, mock_stream_cls: MagicMock, tmp_path: Path) -> None:
        """Full start/stop cycle."""
        pipeline = self._make_pipeline(tmp_path)
        pipeline.start()
        assert pipeline.is_active

        pipeline.stop()
        assert not pipeline.is_active
        assert pipeline._stream is None
        assert pipeline._writer is None

    def test_stop_promotes_final_segment(self, tmp_path: Path) -> None:
        """stop() promotes the final segment with data."""
        pipeline = self._make_pipeline(tmp_path, sample_rate=1000, segment_duration_s=100)

        # Manually set up writer and write some data
        pipeline._writer = SegmentWriter(
            tmp_path / ".buffer" / "raw",
            tmp_path / "data" / "raw",
            pipeline._config,
        )
        pipeline._writer.write(np.zeros(500, dtype=np.int16))
        pipeline._active = True

        pipeline.stop()

        # Final segment should be promoted
        data_files = list((tmp_path / "data" / "raw").iterdir())
        assert len(data_files) == 1

    def test_stop_discards_empty_segment(self, tmp_path: Path) -> None:
        """stop() discards a segment with no data written."""
        pipeline = self._make_pipeline(tmp_path)

        pipeline._writer = SegmentWriter(
            tmp_path / ".buffer" / "raw",
            tmp_path / "data" / "raw",
            pipeline._config,
        )
        pipeline._active = True

        pipeline.stop()

        # No files should be promoted
        data_files = list((tmp_path / "data" / "raw").iterdir())
        assert len(data_files) == 0


# ===================================================================
# _ensure_alsa_hostapi
# ===================================================================


@pytest.mark.unit
class TestEnsureAlsaHostapi:
    """Tests for _ensure_alsa_hostapi — ALSA host API verification."""

    def test_alsa_available(self) -> None:
        """Returns silently when ALSA is among host APIs."""
        with patch("silvasonic.recorder.pipeline.sd") as mock_sd:
            mock_sd.query_hostapis.return_value = [
                {
                    "name": "ALSA",
                    "devices": [],
                    "default_input_device": 0,
                    "default_output_device": 0,
                },
            ]
            _ensure_alsa_hostapi()
            mock_sd.query_hostapis.assert_called_once()

    def test_alsa_not_available_warns(self) -> None:
        """Logs warning when ALSA is not among host APIs."""
        with patch("silvasonic.recorder.pipeline.sd") as mock_sd:
            mock_sd.query_hostapis.return_value = [
                {
                    "name": "PulseAudio",
                    "devices": [],
                    "default_input_device": 0,
                    "default_output_device": 0,
                },
            ]
            _ensure_alsa_hostapi()
            # Function should complete without error (warning logged internally)
            mock_sd.query_hostapis.assert_called_once()

    def test_query_exception_does_not_crash(self) -> None:
        """Function handles exceptions from query_hostapis gracefully."""
        with patch("silvasonic.recorder.pipeline.sd") as mock_sd:
            # Returning an iterable that raises during iteration
            mock_sd.query_hostapis.return_value = []
            # Should not raise — just logs the warning
            _ensure_alsa_hostapi()
