"""Unit tests for the Indexer module.

Tests WAV metadata extraction, path parsing, timestamp parsing,
idempotency, and workspace scanning — all without a real DB.
"""

from __future__ import annotations

import wave
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from silvasonic.processor import indexer


def _create_wav(path: Path, *, duration_s: float = 1.0, sample_rate: int = 48000) -> None:
    """Create a minimal valid WAV file for testing."""
    n_frames = int(duration_s * sample_rate)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        # Write silence (zeros)
        wf.writeframes(b"\x00\x00" * n_frames)


@pytest.mark.unit
class TestScanWorkspace:
    """Verify workspace scanning logic."""

    def test_discovers_processed_wavs(self, tmp_path: Path) -> None:
        """Scan finds WAV files in */data/processed/ directories."""
        dev_dir = tmp_path / "mic-01" / "data" / "processed"
        dev_dir.mkdir(parents=True)
        wav = dev_dir / "2026-03-26T01-35-00_10s.wav"
        _create_wav(wav)

        result = indexer.scan_workspace(tmp_path)
        assert len(result) == 1
        assert result[0] == wav

    def test_buffer_dir_excluded(self, tmp_path: Path) -> None:
        """Files in .buffer/ directories are never returned."""
        buf_dir = tmp_path / "mic-01" / ".buffer" / "processed"
        buf_dir.mkdir(parents=True)
        _create_wav(buf_dir / "2026-03-26T01-35-00_10s.wav")

        result = indexer.scan_workspace(tmp_path)
        assert len(result) == 0

    def test_only_data_dir_scanned(self, tmp_path: Path) -> None:
        """Only */data/processed/*.wav is matched, not parent or sibling dirs."""
        # File in root — should not match
        _create_wav(tmp_path / "stray.wav")
        # File in data/ (not data/processed/) — should not match
        other = tmp_path / "mic-01" / "data" / "raw"
        other.mkdir(parents=True)
        _create_wav(other / "test.wav")

        result = indexer.scan_workspace(tmp_path)
        assert len(result) == 0

    def test_multiple_sensors_discovered(self, tmp_path: Path) -> None:
        """Files from multiple sensor directories are all discovered."""
        for name in ("mic-01", "mic-02"):
            d = tmp_path / name / "data" / "processed"
            d.mkdir(parents=True)
            _create_wav(d / "2026-03-26T01-35-00_10s.wav")

        result = indexer.scan_workspace(tmp_path)
        assert len(result) == 2


@pytest.mark.unit
class TestParseTimestamp:
    """Verify timestamp extraction from filenames."""

    def test_standard_filename(self) -> None:
        """Parse ISO-timestamp from standard segment filename."""
        ts = indexer.parse_timestamp("2026-03-26T01-35-00_10s.wav")
        assert ts == datetime(2026, 3, 26, 1, 35, 0, tzinfo=UTC)

    def test_different_duration(self) -> None:
        """Duration suffix doesn't affect timestamp parsing."""
        ts = indexer.parse_timestamp("2026-01-01T00-00-00_30s.wav")
        assert ts == datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    def test_invalid_format_raises(self) -> None:
        """Non-matching filename raises ValueError."""
        with pytest.raises(ValueError):
            indexer.parse_timestamp("not_a_timestamp.wav")


@pytest.mark.unit
class TestExtractMetadata:
    """Verify WAV metadata extraction via soundfile."""

    def test_wav_metadata_extraction(self, tmp_path: Path) -> None:
        """Extracted metadata matches the synthetic WAV properties."""
        wav = tmp_path / "test.wav"
        _create_wav(wav, duration_s=2.0, sample_rate=48000)

        meta = indexer.extract_metadata(wav)
        assert meta.sample_rate == 48000
        assert abs(meta.duration - 2.0) < 0.01
        assert meta.filesize > 0


@pytest.mark.unit
class TestResolveSensorId:
    """Verify sensor_id extraction from path structure."""

    def test_sensor_id_from_path(self, tmp_path: Path) -> None:
        """Path .../recorder/ultramic-01/data/processed/seg.wav → 'ultramic-01'."""
        wav = tmp_path / "ultramic-01" / "data" / "processed" / "seg.wav"
        sensor_id = indexer.resolve_sensor_id(wav, tmp_path)
        assert sensor_id == "ultramic-01"


@pytest.mark.unit
class TestResolveRawPath:
    """Verify processed → raw path resolution."""

    def test_raw_file_path_resolution(self) -> None:
        """Replaces /data/processed/ with /data/raw/ in path."""
        processed = Path("/data/recorder/mic-01/data/processed/seg.wav")
        raw = indexer.resolve_raw_path(processed)
        assert raw == Path("/data/recorder/mic-01/data/raw/seg.wav")


@pytest.mark.unit
class TestIdempotency:
    """Verify that existing entries are skipped."""

    async def test_idempotent_skip_existing(self, tmp_path: Path) -> None:
        """File already in DB (mocked fetchone returns row) is not re-inserted."""
        dev_dir = tmp_path / "mic-01" / "data" / "processed"
        dev_dir.mkdir(parents=True)
        _create_wav(dev_dir / "2026-03-26T01-35-00_10s.wav")

        # Mock session that says "row exists"
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1,)  # Row exists

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        result = await indexer.index_recordings(session, tmp_path)
        assert result.skipped == 1
        assert result.new == 0
        # commit should NOT be called (no new rows)
        session.commit.assert_not_called()
