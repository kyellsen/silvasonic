"""Unit tests for silvasonic.recorder.ffmpeg_pipeline module.

Tests FFmpegConfig, SegmentPromoter, and FFmpegPipeline with mocked
FFmpeg subprocess — no real audio hardware or FFmpeg binary needed.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from silvasonic.recorder.ffmpeg_pipeline import (
    _ALSA_FORMAT_MAP,
    _FFMPEG_CODEC_MAP,
    PROCESSED_SAMPLE_RATE,
    FFmpegConfig,
    FFmpegPipeline,
    SegmentPromoter,
)

# ===================================================================
# FFmpegConfig
# ===================================================================


@pytest.mark.unit
class TestFFmpegConfig:
    """Tests for FFmpegConfig — validated capture parameters."""

    def test_defaults(self) -> None:
        """Default config matches ADR-0011 processed target."""
        cfg = FFmpegConfig()
        assert cfg.sample_rate == 48000
        assert cfg.channels == 1
        assert cfg.format == "S16LE"
        assert cfg.segment_duration_s == 10
        assert cfg.gain_db == 0.0
        assert cfg.raw_enabled is True
        assert cfg.processed_enabled is True

    def test_from_profile(self) -> None:
        """from_profile extracts all fields from a MicrophoneProfile."""
        profile = MagicMock()
        profile.audio.sample_rate = 384000
        profile.audio.channels = 1
        profile.audio.format = "S24LE"
        profile.processing.gain_db = 6.0
        profile.processing.chunk_size = 8192
        profile.stream.segment_duration_s = 30
        profile.stream.raw_enabled = True
        profile.stream.processed_enabled = False

        cfg = FFmpegConfig.from_profile(profile)
        assert cfg.sample_rate == 384000
        assert cfg.channels == 1
        assert cfg.format == "S24LE"
        assert cfg.gain_db == 6.0
        assert cfg.segment_duration_s == 30
        assert cfg.raw_enabled is True
        assert cfg.processed_enabled is False

    def test_ffmpeg_codec_s16le(self) -> None:
        """S16LE maps to pcm_s16le."""
        cfg = FFmpegConfig(format="S16LE")
        assert cfg.ffmpeg_codec == "pcm_s16le"

    def test_ffmpeg_codec_s24le(self) -> None:
        """S24LE maps to pcm_s24le."""
        cfg = FFmpegConfig(format="S24LE")
        assert cfg.ffmpeg_codec == "pcm_s24le"

    def test_ffmpeg_codec_s32le(self) -> None:
        """S32LE maps to pcm_s32le."""
        cfg = FFmpegConfig(format="S32LE")
        assert cfg.ffmpeg_codec == "pcm_s32le"

    def test_alsa_format(self) -> None:
        """ALSA format map is consistent."""
        for fmt, expected in _ALSA_FORMAT_MAP.items():
            cfg = FFmpegConfig(format=fmt)
            assert cfg.alsa_format == expected

    def test_codec_map_complete(self) -> None:
        """Every supported format has an FFmpeg codec mapping."""
        for fmt in ("S16LE", "S24LE", "S32LE"):
            assert fmt in _FFMPEG_CODEC_MAP

    def test_volume_filter_zero_gain(self) -> None:
        """Zero gain returns None (no filter needed)."""
        cfg = FFmpegConfig(gain_db=0.0)
        assert cfg.ffmpeg_volume_filter is None

    def test_volume_filter_nonzero_gain(self) -> None:
        """Non-zero gain returns the volume filter string."""
        cfg = FFmpegConfig(gain_db=6.0)
        assert cfg.ffmpeg_volume_filter == "volume=6.0dB"

    def test_build_ffmpeg_args_mock_source(self) -> None:
        """Mock source uses lavfi sine generator."""
        cfg = FFmpegConfig(sample_rate=48000, channels=1, format="S16LE")
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/app/ws"), mock_source=True)

        assert "-f" in args
        assert "lavfi" in args
        assert any("sine=" in a for a in args)
        assert "-re" in args  # Force real-time processing
        assert "-f" in args
        assert "alsa" not in args

    def test_build_ffmpeg_args_alsa_source(self) -> None:
        """ALSA source uses the device string."""
        cfg = FFmpegConfig(sample_rate=384000, channels=1, format="S24LE")
        args = cfg.build_ffmpeg_args("hw:2,0", Path("/app/ws"), mock_source=False)

        assert "alsa" in args
        assert "hw:2,0" in args
        assert "384000" in args

    def test_build_ffmpeg_args_dual_stream(self) -> None:
        """Dual stream produces two -map 0:a outputs."""
        cfg = FFmpegConfig(raw_enabled=True, processed_enabled=True)
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), mock_source=True)

        map_count = args.count("-map")
        assert map_count == 2, f"Expected 2 -map flags, got {map_count}"

    def test_build_ffmpeg_args_raw_only(self) -> None:
        """Raw-only produces one -map 0:a output."""
        cfg = FFmpegConfig(raw_enabled=True, processed_enabled=False)
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), mock_source=True)

        map_count = args.count("-map")
        assert map_count == 1

    def test_build_ffmpeg_args_processed_only(self) -> None:
        """Processed-only produces one -map 0:a output with -ar 48000."""
        cfg = FFmpegConfig(raw_enabled=False, processed_enabled=True)
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), mock_source=True)

        map_count = args.count("-map")
        assert map_count == 1
        assert str(PROCESSED_SAMPLE_RATE) in args

    def test_build_ffmpeg_args_with_gain(self) -> None:
        """Non-zero gain adds -af volume filter."""
        cfg = FFmpegConfig(gain_db=12.0)
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), mock_source=True)

        assert "-af" in args
        af_idx = args.index("-af")
        assert "volume=12.0dB" in args[af_idx + 1]

    def test_build_ffmpeg_args_no_gain(self) -> None:
        """Zero gain omits -af filter."""
        cfg = FFmpegConfig(gain_db=0.0)
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), mock_source=True)

        assert "-af" not in args

    def test_build_ffmpeg_args_segment_options(self) -> None:
        """Segment muxer options are present."""
        cfg = FFmpegConfig(segment_duration_s=15)
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), mock_source=True)

        assert "-f" in args
        assert "segment" in args
        assert "-segment_time" in args
        seg_idx = args.index("-segment_time")
        assert args[seg_idx + 1] == "15"
        assert "-reset_timestamps" in args
        assert "-segment_list_type" in args

    def test_build_ffmpeg_args_custom_binary(self) -> None:
        """Custom FFmpeg binary path is used."""
        cfg = FFmpegConfig()
        args = cfg.build_ffmpeg_args(
            "hw:1,0", Path("/ws"), mock_source=True, ffmpeg_binary="/usr/local/bin/ffmpeg"
        )
        assert args[0] == "/usr/local/bin/ffmpeg"


# ===================================================================
# SegmentPromoter
# ===================================================================


@pytest.mark.unit
class TestSegmentPromoter:
    """Tests for SegmentPromoter — CSV poll + atomic promotion."""

    def _write_csv(self, csv_path: Path, rows: list[list[str]]) -> None:
        """Helper to write a segment-list CSV."""
        with csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            for row in rows:
                writer.writerow(row)

    def test_promotes_segment(self, tmp_path: Path) -> None:
        """Segments listed in CSV are promoted from .buffer/ to data/."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        csv_path = tmp_path / ".buffer" / "raw_segments.csv"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        # Create a "completed" segment in buffer
        seg_file = buffer_dir / "2026-03-25T14-30-00_10s.wav"
        seg_file.write_text("fake wav data")

        # Write the CSV (FFmpeg would do this)
        self._write_csv(
            csv_path,
            [
                [str(seg_file), "0.000000", "10.000000"],
            ],
        )

        promoter = SegmentPromoter(csv_path, buffer_dir, data_dir, stream_name="raw")
        promoter._poll_and_promote()

        assert not seg_file.exists(), "Source should be moved"
        assert (data_dir / "2026-03-25T14-30-00_10s.wav").exists()
        assert promoter.segments_promoted == 1

    def test_idempotent_double_poll(self, tmp_path: Path) -> None:
        """Polling twice with the same CSV does not re-promote."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        csv_path = tmp_path / ".buffer" / "raw_segments.csv"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        seg_file = buffer_dir / "seg1.wav"
        seg_file.write_text("data")

        self._write_csv(csv_path, [[str(seg_file), "0", "10"]])

        promoter = SegmentPromoter(csv_path, buffer_dir, data_dir)
        promoter._poll_and_promote()
        promoter._poll_and_promote()  # Second poll — no new lines

        assert promoter.segments_promoted == 1

    def test_missing_source_logs_warning(self, tmp_path: Path) -> None:
        """Missing source file is logged but does not crash."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        csv_path = tmp_path / ".buffer" / "raw_segments.csv"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        # CSV references a non-existent file
        self._write_csv(
            csv_path,
            [
                [str(buffer_dir / "nonexistent.wav"), "0", "10"],
            ],
        )

        promoter = SegmentPromoter(csv_path, buffer_dir, data_dir)
        promoter._poll_and_promote()

        assert promoter.segments_promoted == 0

    def test_no_csv_is_safe(self, tmp_path: Path) -> None:
        """No CSV file is a no-op (FFmpeg hasn't written one yet)."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        csv_path = tmp_path / ".buffer" / "raw_segments.csv"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        promoter = SegmentPromoter(csv_path, buffer_dir, data_dir)
        promoter._poll_and_promote()

        assert promoter.segments_promoted == 0

    def test_incremental_csv_growth(self, tmp_path: Path) -> None:
        """New CSV lines are promoted incrementally."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        csv_path = tmp_path / ".buffer" / "raw_segments.csv"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        # First segment
        seg1 = buffer_dir / "seg1.wav"
        seg1.write_text("data1")
        self._write_csv(csv_path, [[str(seg1), "0", "10"]])

        promoter = SegmentPromoter(csv_path, buffer_dir, data_dir)
        promoter._poll_and_promote()
        assert promoter.segments_promoted == 1

        # Second segment added
        seg2 = buffer_dir / "seg2.wav"
        seg2.write_text("data2")
        self._write_csv(
            csv_path,
            [
                [str(seg1), "0", "10"],
                [str(seg2), "10", "20"],
            ],
        )

        promoter._poll_and_promote()
        assert promoter.segments_promoted == 2
        assert (data_dir / "seg2.wav").exists()

    def test_thread_lifecycle(self, tmp_path: Path) -> None:
        """Promoter thread starts, runs, and stops cleanly."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        csv_path = tmp_path / ".buffer" / "raw_segments.csv"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        promoter = SegmentPromoter(csv_path, buffer_dir, data_dir, poll_interval=0.1)
        promoter.start()
        assert promoter.is_alive()

        promoter.stop()
        promoter.join(timeout=2)
        assert not promoter.is_alive()


# ===================================================================
# FFmpegPipeline
# ===================================================================


@pytest.mark.unit
class TestFFmpegPipeline:
    """Tests for FFmpegPipeline — subprocess lifecycle management."""

    def _make_workspace(self, tmp_path: Path) -> Path:
        """Create a minimal workspace structure."""
        for subdir in ("data/raw", "data/processed", ".buffer/raw", ".buffer/processed"):
            (tmp_path / subdir).mkdir(parents=True, exist_ok=True)
        return tmp_path

    def test_initial_state(self, tmp_path: Path) -> None:
        """Pipeline is inactive before start()."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig()
        pipeline = FFmpegPipeline(config, ws)

        assert not pipeline.is_active
        assert pipeline.segments_promoted == 0
        assert pipeline.ffmpeg_pid is None
        assert pipeline.stderr_errors == []

    @patch("silvasonic.recorder.ffmpeg_pipeline.SegmentPromoter")
    def test_start_creates_subprocess(self, mock_promoter: MagicMock, tmp_path: Path) -> None:
        """start() launches an FFmpeg subprocess."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig(segment_duration_s=5)

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None  # Process running
        mock_proc.stderr = iter([])  # Empty stderr

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc):
            pipeline = FFmpegPipeline(config, ws, mock_source=True)
            pipeline.start()

        assert pipeline.is_active
        assert pipeline.ffmpeg_pid == 12345

        # Clean up
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        pipeline.stop()

    @patch("silvasonic.recorder.ffmpeg_pipeline.SegmentPromoter")
    def test_stop_sends_sigint(self, mock_promoter: MagicMock, tmp_path: Path) -> None:
        """stop() sends SIGINT for clean FFmpeg shutdown."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig()

        mock_proc = MagicMock()
        mock_proc.pid = 99
        mock_proc.poll.side_effect = [None, 0]  # Running, then exited
        mock_proc.returncode = 0
        mock_proc.stderr = iter([])

        import signal

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc):
            pipeline = FFmpegPipeline(config, ws, mock_source=True)
            pipeline.start()
            pipeline.stop()

        mock_proc.send_signal.assert_called_once_with(signal.SIGINT)

    @patch("silvasonic.recorder.ffmpeg_pipeline.SegmentPromoter")
    def test_segments_promoted_property(self, mock_promoter: MagicMock, tmp_path: Path) -> None:
        """segments_promoted aggregates both streams."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig(raw_enabled=True, processed_enabled=True)

        mock_proc = MagicMock()
        mock_proc.pid = 1
        mock_proc.poll.return_value = None
        mock_proc.stderr = iter([])

        # Configure mock promoters with segments_promoted property
        raw_promoter = MagicMock()
        raw_promoter.segments_promoted = 5
        processed_promoter = MagicMock()
        processed_promoter.segments_promoted = 3
        mock_promoter.side_effect = [raw_promoter, processed_promoter]

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc):
            pipeline = FFmpegPipeline(config, ws, mock_source=True)
            pipeline.start()

        assert pipeline.segments_promoted == 8
        assert pipeline.raw_segments_promoted == 5
        assert pipeline.processed_segments_promoted == 3

        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        pipeline.stop()

    def test_stderr_monitoring(self, tmp_path: Path) -> None:
        """Stderr lines with error/warning are captured."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig(raw_enabled=False, processed_enabled=False)

        stderr_lines = [
            b"[alsa] ALSA buffer xrun detected\n",
            b"normal debug line\n",
            b"[warning] something went wrong\n",
        ]

        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.poll.return_value = None
        mock_proc.stderr = iter(stderr_lines)
        mock_proc.returncode = 0

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc):
            pipeline = FFmpegPipeline(config, ws, mock_source=True)
            pipeline.start()

        # Wait for stderr thread to finish processing mock data
        if pipeline._stderr_thread is not None:
            pipeline._stderr_thread.join(timeout=2)

        errors = pipeline.stderr_errors
        assert len(errors) == 2
        assert any("xrun" in e for e in errors)
        assert any("warning" in e for e in errors)

        mock_proc.poll.return_value = 0
        pipeline.stop()

    @patch("silvasonic.recorder.ffmpeg_pipeline.SegmentPromoter")
    def test_clean_segment_lists_on_start(self, mock_promoter: MagicMock, tmp_path: Path) -> None:
        """Stale segment CSVs are removed on start()."""
        ws = self._make_workspace(tmp_path)
        raw_csv = ws / ".buffer" / "raw_segments.csv"
        proc_csv = ws / ".buffer" / "processed_segments.csv"
        raw_csv.write_text("stale data")
        proc_csv.write_text("stale data")

        config = FFmpegConfig()

        mock_proc = MagicMock()
        mock_proc.pid = 1
        mock_proc.poll.return_value = None
        mock_proc.stderr = iter([])

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc):
            pipeline = FFmpegPipeline(config, ws, mock_source=True)
            pipeline.start()

        assert not raw_csv.exists()
        assert not proc_csv.exists()

        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        pipeline.stop()

    @patch("silvasonic.recorder.ffmpeg_pipeline.SegmentPromoter")
    def test_raw_disabled_no_raw_promoter(self, mock_promoter: MagicMock, tmp_path: Path) -> None:
        """When raw_enabled=False, no raw promoter is created."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig(raw_enabled=False, processed_enabled=True)

        mock_proc = MagicMock()
        mock_proc.pid = 1
        mock_proc.poll.return_value = None
        mock_proc.stderr = iter([])

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc):
            pipeline = FFmpegPipeline(config, ws, mock_source=True)
            pipeline.start()

        # raw_promoter should not be created, but processed should
        assert pipeline._raw_promoter is None
        assert pipeline._processed_promoter is not None

        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        pipeline.stop()

    @patch("silvasonic.recorder.ffmpeg_pipeline.SegmentPromoter")
    def test_processed_disabled_no_processed_promoter(
        self, mock_promoter: MagicMock, tmp_path: Path
    ) -> None:
        """When processed_enabled=False, no processed promoter is created."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig(raw_enabled=True, processed_enabled=False)

        mock_proc = MagicMock()
        mock_proc.pid = 1
        mock_proc.poll.return_value = None
        mock_proc.stderr = iter([])

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc):
            pipeline = FFmpegPipeline(config, ws, mock_source=True)
            pipeline.start()

        # processed_promoter should not be created, but raw should
        assert pipeline._raw_promoter is not None
        assert pipeline._processed_promoter is None

        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        pipeline.stop()
