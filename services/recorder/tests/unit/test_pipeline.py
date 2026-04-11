"""Unit tests for silvasonic.recorder.ffmpeg_pipeline module.

Tests FFmpegConfig, SegmentPromoter, and FFmpegPipeline with mocked
FFmpeg subprocess — no real audio hardware or FFmpeg binary needed.
"""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from silvasonic.recorder.ffmpeg_pipeline import (
    _ALSA_FORMAT_MAP,
    PROCESSED_SAMPLE_RATE,
    FFmpegConfig,
    FFmpegPipeline,
    SegmentPromoter,
    TimestampRegistry,
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

    def test_from_injected_config(self) -> None:
        """from_injected_config extracts all fields from an RecorderRuntimeConfig."""
        config = MagicMock()
        config.audio.sample_rate = 384000
        config.audio.channels = 1
        config.audio.format = "S24LE"
        config.processing.gain_db = 6.0
        config.stream.segment_duration_s = 30
        config.stream.raw_enabled = True
        config.stream.processed_enabled = False

        cfg = FFmpegConfig.from_injected_config(config)
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
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/app/ws"), run_id="123", mock_source=True)

        assert "-f" in args
        assert "lavfi" in args
        assert any("sine=" in a for a in args)
        assert "-re" in args  # Force real-time processing
        assert "-f" in args
        assert "alsa" not in args

    def test_build_ffmpeg_args_alsa_source(self) -> None:
        """ALSA source uses the device string."""
        cfg = FFmpegConfig(sample_rate=384000, channels=1, format="S24LE")
        args = cfg.build_ffmpeg_args("hw:2,0", Path("/app/ws"), run_id="123", mock_source=False)

        assert "alsa" in args
        assert "hw:2,0" in args
        assert "384000" in args

    def test_build_ffmpeg_args_dual_stream(self) -> None:
        """Dual stream produces two -map 0:a outputs."""
        cfg = FFmpegConfig(raw_enabled=True, processed_enabled=True)
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), run_id="123", mock_source=True)

        map_count = args.count("-map")
        assert map_count == 2, f"Expected 2 -map flags, got {map_count}"

    def test_build_ffmpeg_args_raw_only(self) -> None:
        """Raw-only produces one -map 0:a output."""
        cfg = FFmpegConfig(raw_enabled=True, processed_enabled=False)
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), run_id="123", mock_source=True)

        map_count = args.count("-map")
        assert map_count == 1

    def test_build_ffmpeg_args_processed_only(self) -> None:
        """Processed-only produces one -map 0:a output with -ar 48000."""
        cfg = FFmpegConfig(raw_enabled=False, processed_enabled=True)
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), run_id="123", mock_source=True)

        map_count = args.count("-map")
        assert map_count == 1
        assert str(PROCESSED_SAMPLE_RATE) in args

    def test_build_ffmpeg_args_with_gain(self) -> None:
        """Non-zero gain adds -af volume filter."""
        cfg = FFmpegConfig(gain_db=12.0)
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), run_id="123", mock_source=True)

        assert "-af" in args
        af_idx = args.index("-af")
        assert "volume=12.0dB" in args[af_idx + 1]

    def test_build_ffmpeg_args_no_gain(self) -> None:
        """Zero gain omits -af filter."""
        cfg = FFmpegConfig(gain_db=0.0)
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), run_id="123", mock_source=True)

        assert "-af" not in args

    def test_build_ffmpeg_args_segment_options(self) -> None:
        """Segment muxer options use run_id and sequence natively."""
        cfg = FFmpegConfig(segment_duration_s=15)
        # Passing run_id is now required to generate safe filenames.
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), mock_source=True, run_id="1a2b3c4d")

        assert "-f" in args
        assert "segment" in args
        assert "-segment_time" in args
        seg_idx = args.index("-segment_time")
        assert args[seg_idx + 1] == "15"

        # Must retain internal pts/dts resets for standard audio playback length!
        assert "-reset_timestamps" in args
        assert args[args.index("-reset_timestamps") + 1] == "1"

        # Naming MUST NOT use strftime anymore!
        assert "-strftime" not in args
        # Output must be run_id separated with integer format
        assert any("1a2b3c4d_%08d.wav" in a for a in args)

    def test_build_ffmpeg_args_no_segment_list(self) -> None:
        """No -segment_list arguments are generated (CSV removed)."""
        cfg = FFmpegConfig()
        args = cfg.build_ffmpeg_args("hw:1,0", Path("/ws"), run_id="123", mock_source=True)

        assert "-segment_list" not in args
        assert "-segment_list_type" not in args

    def test_build_ffmpeg_args_custom_binary(self) -> None:
        """Custom FFmpeg binary path is used."""
        cfg = FFmpegConfig()
        args = cfg.build_ffmpeg_args(
            "hw:1,0",
            Path("/ws"),
            run_id="123",
            mock_source=True,
            ffmpeg_binary="/usr/local/bin/ffmpeg",
        )
        assert args[0] == "/usr/local/bin/ffmpeg"


# ===================================================================
# TimestampRegistry
# ===================================================================


@pytest.mark.unit
class TestTimestampRegistry:
    """Tests for TimestampRegistry (Tuple Key & Eviction)."""

    def test_tuple_key_deterministic_time(self) -> None:
        """Registry guarantees exact same timestamp for (run_id, seq)."""
        registry = TimestampRegistry()
        key1 = ("1a2b3c4d", 0)

        # First query inserts the time
        ts1 = registry.get_timestamp(key1)
        # Second query simply fetches the exact same time
        ts2 = registry.get_timestamp(key1)
        assert ts1 == ts2

        # A different seq or run_id might produce a different timestamp (mocking sleep ideally)
        key2 = ("1a2b3c4d", 1)
        ts3 = registry.get_timestamp(key2)
        assert isinstance(ts3, str)
        assert "Z" in ts3

    def test_evicts_old_entries(self) -> None:
        """Registry clears oldest elements when exceeding 128 elements."""
        registry = TimestampRegistry()
        for i in range(130):
            registry.get_timestamp(("run_x", i))

        # Size should be clamped to 128
        assert len(registry._times) == 128
        # Sequence 0 and 1 should be gone
        assert ("run_x", 0) not in registry._times
        assert ("run_x", 1) not in registry._times


# ===================================================================
# SegmentPromoter
# ===================================================================


@pytest.mark.unit
class TestSegmentPromoter:
    """Tests for SegmentPromoter — filesystem poll + atomic promotion."""

    def test_promotes_completed_segment_with_registry(self, tmp_path: Path) -> None:
        """Older file is promoted and renamed securely via registry."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        # Fake raw outputs generated by FFmpeg using the new run_id_%08d schema
        seg1 = buffer_dir / "1a2b3c4d_00000000.wav"
        seg2 = buffer_dir / "1a2b3c4d_00000001.wav"
        seg1.write_text("complete segment")
        seg2.write_text("active segment")

        mock_registry = MagicMock()
        mock_registry.get_timestamp.return_value = "2026-03-30T10-30-00Z"

        promoter = SegmentPromoter(
            buffer_dir, data_dir, stream_name="raw", segment_duration_s=10, registry=mock_registry
        )
        promoter._poll_and_promote()

        assert not seg1.exists(), "Completed segment should be moved"
        assert seg2.exists(), "Active segment should remain"

        # Target must now combine stamp, stream details and origin IDs
        expected_target = data_dir / "2026-03-30T10-30-00Z_10s_1a2b3c4d_00000000.wav"
        assert expected_target.exists()
        assert promoter.segments_promoted == 1

        mock_registry.get_timestamp.assert_called_once_with(("1a2b3c4d", 0))

    def test_skips_single_file(self, tmp_path: Path) -> None:
        """When only 1 file exists, nothing is promoted (still active)."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        active = buffer_dir / "seg1.wav"
        active.write_text("being written")

        promoter = SegmentPromoter(buffer_dir, data_dir)
        promoter._poll_and_promote()

        assert active.exists(), "Active segment must not be promoted"
        assert promoter.segments_promoted == 0

    def test_empty_buffer_is_safe(self, tmp_path: Path) -> None:
        """Empty buffer directory is a no-op."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        promoter = SegmentPromoter(buffer_dir, data_dir)
        promoter._poll_and_promote()

        assert promoter.segments_promoted == 0

    def test_incremental_promotion(self, tmp_path: Path) -> None:
        """New segments are promoted incrementally as they appear."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        # First round: 2 files → promote oldest
        seg1 = buffer_dir / "seg1.wav"
        seg2 = buffer_dir / "seg2.wav"
        seg1.write_text("data1")
        seg2.write_text("data2")

        promoter = SegmentPromoter(buffer_dir, data_dir)
        promoter._poll_and_promote()
        assert promoter.segments_promoted == 1
        assert (data_dir / "seg1.wav").exists()

        # Second round: seg3 appears → seg2 can be promoted
        seg3 = buffer_dir / "seg3.wav"
        seg3.write_text("data3")

        promoter._poll_and_promote()
        assert promoter.segments_promoted == 2
        assert (data_dir / "seg2.wav").exists()
        assert seg3.exists(), "Newest file (active) should remain"

    def test_promotes_multiple_at_once(self, tmp_path: Path) -> None:
        """When multiple completed segments accumulate, all are promoted."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        # 4 files: 3 complete + 1 active
        for i in range(4):
            (buffer_dir / f"seg{i:02d}.wav").write_text(f"data{i}")

        promoter = SegmentPromoter(buffer_dir, data_dir)
        promoter._poll_and_promote()

        assert promoter.segments_promoted == 3
        assert (buffer_dir / "seg03.wav").exists(), "Newest must remain"

    def test_final_pass_promotes_all(self, tmp_path: Path) -> None:
        """After FFmpeg exits, _promote_all() promotes all remaining files properly."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        seg1 = buffer_dir / "1a2b3c4d_00000000.wav"
        seg2 = buffer_dir / "1a2b3c4d_00000001.wav"
        seg1.write_text("data1")
        seg2.write_text("data2")

        mock_registry = MagicMock()
        mock_registry.get_timestamp.side_effect = ["2026-03-30T10-30-00Z", "2026-03-30T10-30-10Z"]

        promoter = SegmentPromoter(buffer_dir, data_dir, stream_name="raw", registry=mock_registry)
        promoter._promote_all()

        assert promoter.segments_promoted == 2
        assert not seg1.exists()
        assert not seg2.exists()
        assert (data_dir / "2026-03-30T10-30-00Z_10s_1a2b3c4d_00000000.wav").exists()
        assert (data_dir / "2026-03-30T10-30-10Z_10s_1a2b3c4d_00000001.wav").exists()

    def test_dual_stream_pairing(self, tmp_path: Path) -> None:
        """Raw and Processed promoters generate identically stamped files for same seq."""
        raw_buffer = tmp_path / ".buffer" / "raw"
        raw_data = tmp_path / "data" / "raw"
        processed_buffer = tmp_path / ".buffer" / "processed"
        processed_data = tmp_path / "data" / "processed"

        for d in (raw_buffer, raw_data, processed_buffer, processed_data):
            d.mkdir(parents=True)

        (raw_buffer / "1a2b3c4d_00000000.wav").write_text("raw1")
        (raw_buffer / "1a2b3c4d_00000001.wav").write_text("raw2")

        (processed_buffer / "1a2b3c4d_00000000.wav").write_text("proc1")
        (processed_buffer / "1a2b3c4d_00000001.wav").write_text("proc2")

        # The real registry shares state between threads
        registry = TimestampRegistry()

        # Both promoters share the same registry reference
        prom_raw = SegmentPromoter(raw_buffer, raw_data, stream_name="raw", registry=registry)
        prom_proc = SegmentPromoter(
            processed_buffer, processed_data, stream_name="processed", registry=registry
        )

        prom_raw._promote_all()
        prom_proc._promote_all()

        assert prom_raw.segments_promoted == 2
        assert prom_proc.segments_promoted == 2

        # We must find perfectly identical file names in both data directories
        raw_files = sorted(f.name for f in raw_data.iterdir())
        proc_files = sorted(f.name for f in processed_data.iterdir())

        assert raw_files == proc_files, "Dual-stream filenames must be 100% identical"
        assert len(raw_files) == 2
        assert "_1a2b3c4d_00000000.wav" in raw_files[0]

    def test_thread_lifecycle(self, tmp_path: Path) -> None:
        """Promoter thread starts, runs, and stops cleanly."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        promoter = SegmentPromoter(buffer_dir, data_dir, poll_interval=0.1)
        promoter.start()
        assert promoter.is_alive()

        promoter.stop()
        promoter.join(timeout=2)
        assert not promoter.is_alive()

    def test_promotes_invalid_filename_as_is(self, tmp_path: Path) -> None:
        """Files with unparseable names are promoted without renaming."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        # Invalid name: no underscore separator → ValueError in split/int()
        invalid = buffer_dir / "000_noseparator.wav"
        valid_active = buffer_dir / "1a2b3c4d_00000001.wav"
        invalid.write_text("orphan data")
        valid_active.write_text("active")

        promoter = SegmentPromoter(buffer_dir, data_dir, stream_name="raw")
        promoter._poll_and_promote()

        # Invalid file promoted as-is (no renaming)
        assert (data_dir / "000_noseparator.wav").exists()
        assert not invalid.exists()
        assert valid_active.exists(), "Active file must stay in buffer"
        assert promoter.segments_promoted == 1

    def test_promotion_calls_stats_record(self, tmp_path: Path) -> None:
        """SegmentPromoter calls stats.record_promotion on successful promote."""
        buffer_dir = tmp_path / ".buffer" / "raw"
        data_dir = tmp_path / "data" / "raw"
        buffer_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        seg1 = buffer_dir / "1a2b3c4d_00000000.wav"
        seg2 = buffer_dir / "1a2b3c4d_00000001.wav"
        seg1.write_text("complete segment data")
        seg2.write_text("active")

        mock_stats = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get_timestamp.return_value = "2026-03-30T10-30-00Z"

        promoter = SegmentPromoter(
            buffer_dir,
            data_dir,
            stream_name="raw",
            registry=mock_registry,
            stats=mock_stats,
        )
        promoter._poll_and_promote()

        mock_stats.record_promotion.assert_called_once()
        call_args = mock_stats.record_promotion.call_args
        assert call_args[0][0] == "raw"  # stream name
        assert "1a2b3c4d_00000000.wav" in call_args[0][1]  # filename
        assert call_args[0][2] > 0  # file_size_bytes > 0


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

        # Only processed promoter should be created (1 item in _promoters)
        assert len(pipeline._promoters) == 1
        mock_promoter.assert_called_once()
        assert mock_promoter.call_args.kwargs["stream_name"] == "processed"

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

        # Only raw promoter should be created (1 item in _promoters)
        assert len(pipeline._promoters) == 1
        mock_promoter.assert_called_once()
        assert mock_promoter.call_args.kwargs["stream_name"] == "raw"

        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        pipeline.stop()

    @patch("silvasonic.recorder.ffmpeg_pipeline.SegmentPromoter")
    def test_returncode_while_running(self, mock_promoter: MagicMock, tmp_path: Path) -> None:
        """Returncode returns poll() result while process is running."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig(raw_enabled=False, processed_enabled=False)

        mock_proc = MagicMock()
        mock_proc.pid = 1
        mock_proc.poll.return_value = None  # Running
        mock_proc.stderr = iter([])

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc):
            pipeline = FFmpegPipeline(config, ws, mock_source=True)
            pipeline.start()

        # While running, returncode delegates to poll()
        assert pipeline.returncode is None

        # After exit, poll() returns the exit code
        mock_proc.poll.return_value = -9
        assert pipeline.returncode == -9

        mock_proc.returncode = -9
        pipeline.stop()

    def test_returncode_after_stop(self, tmp_path: Path) -> None:
        """Returncode returns _last_returncode after stop() clears _proc."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig(raw_enabled=False, processed_enabled=False)

        mock_proc = MagicMock()
        mock_proc.pid = 1
        mock_proc.poll.return_value = None  # Running
        mock_proc.stderr = iter([])
        mock_proc.returncode = 42  # Set after wait() in real life

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc):
            pipeline = FFmpegPipeline(config, ws, mock_source=True)
            pipeline.start()

        # poll() returns None → stop() enters the cleanup block → sets _last_returncode
        pipeline.stop()

        # After stop, _proc is None, but _last_returncode persists
        assert pipeline._proc is None
        assert pipeline.returncode == 42

    def test_returncode_initial_none(self, tmp_path: Path) -> None:
        """Returncode is None before any process has started."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig()
        pipeline = FFmpegPipeline(config, ws)
        assert pipeline.returncode is None

    @patch("silvasonic.recorder.ffmpeg_pipeline.SegmentPromoter")
    def test_reentrant_start_clears_stderr(self, mock_promoter: MagicMock, tmp_path: Path) -> None:
        """start() clears previous stderr_errors for re-entrant lifecycle."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig(raw_enabled=False, processed_enabled=False)

        mock_proc = MagicMock()
        mock_proc.pid = 1
        mock_proc.poll.return_value = None
        mock_proc.stderr = iter([b"[error] first run problem\n"])
        mock_proc.returncode = 0

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc):
            pipeline = FFmpegPipeline(config, ws, mock_source=True)
            pipeline.start()

            # Wait for stderr thread to process
            if pipeline._stderr_thread is not None:
                pipeline._stderr_thread.join(timeout=2)

            assert len(pipeline.stderr_errors) >= 1

            # Stop and restart
            mock_proc.poll.return_value = 0
            pipeline.stop()

            mock_proc2 = MagicMock()
            mock_proc2.pid = 2
            mock_proc2.poll.return_value = None
            mock_proc2.stderr = iter([])  # Clean run

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc2):
            pipeline.start()

        # After re-start, old errors should be cleared
        assert pipeline.stderr_errors == []

        mock_proc2.poll.return_value = 0
        mock_proc2.returncode = 0
        pipeline.stop()

    @patch("silvasonic.recorder.ffmpeg_pipeline.SegmentPromoter")
    def test_stop_sigterm_fallback(self, mock_promoter: MagicMock, tmp_path: Path) -> None:
        """stop() escalates to SIGTERM when SIGINT wait times out."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig(raw_enabled=False, processed_enabled=False)

        mock_proc = MagicMock()
        mock_proc.pid = 1
        mock_proc.poll.return_value = None  # Process running
        mock_proc.stderr = iter([])
        # SIGINT → wait() times out, then SIGTERM → wait() succeeds
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired("ffmpeg", 5),  # After SIGINT
            None,  # After SIGTERM
        ]
        mock_proc.returncode = -15

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc):
            pipeline = FFmpegPipeline(config, ws, mock_source=True)
            pipeline.start()
            pipeline.stop()

        mock_proc.send_signal.assert_called_once_with(signal.SIGINT)
        mock_proc.terminate.assert_called_once()

    @patch("silvasonic.recorder.ffmpeg_pipeline.SegmentPromoter")
    def test_stop_sigkill_fallback(self, mock_promoter: MagicMock, tmp_path: Path) -> None:
        """stop() escalates to SIGKILL when both SIGINT and SIGTERM time out."""
        ws = self._make_workspace(tmp_path)
        config = FFmpegConfig(raw_enabled=False, processed_enabled=False)

        mock_proc = MagicMock()
        mock_proc.pid = 1
        mock_proc.poll.return_value = None
        mock_proc.stderr = iter([])
        # SIGINT times out, SIGTERM times out, SIGKILL succeeds
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired("ffmpeg", 5),  # After SIGINT
            subprocess.TimeoutExpired("ffmpeg", 3),  # After SIGTERM
            None,  # After SIGKILL
        ]
        mock_proc.returncode = -9

        with patch("silvasonic.recorder.ffmpeg_pipeline.subprocess.Popen", return_value=mock_proc):
            pipeline = FFmpegPipeline(config, ws, mock_source=True)
            pipeline.start()
            pipeline.stop()

        mock_proc.send_signal.assert_called_once_with(signal.SIGINT)
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
