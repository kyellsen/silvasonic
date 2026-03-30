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
        wav = dev_dir / "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav"
        _create_wav(wav)

        result = indexer.scan_workspace(tmp_path)
        assert len(result) == 1
        assert result[0] == wav

    def test_buffer_dir_excluded(self, tmp_path: Path) -> None:
        """Files in .buffer/ directories are never returned."""
        buf_dir = tmp_path / "mic-01" / ".buffer" / "processed"
        buf_dir.mkdir(parents=True)
        _create_wav(buf_dir / "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav")

        result = indexer.scan_workspace(tmp_path)
        assert len(result) == 0

    def test_only_data_dir_scanned(self, tmp_path: Path) -> None:
        """Only */data/{processed,raw}/*.wav is matched, not stray files."""
        # File in root — should not match
        _create_wav(tmp_path / "stray.wav")

        result = indexer.scan_workspace(tmp_path)
        assert len(result) == 0

    def test_multiple_sensors_discovered(self, tmp_path: Path) -> None:
        """Files from multiple sensor directories are all discovered."""
        for name in ("mic-01", "mic-02"):
            d = tmp_path / name / "data" / "processed"
            d.mkdir(parents=True)
            _create_wav(d / "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav")

        result = indexer.scan_workspace(tmp_path)
        assert len(result) == 2


@pytest.mark.unit
class TestParseTimestamp:
    """Verify timestamp extraction from filenames."""

    @pytest.mark.parametrize(
        ("filename", "expected_ts"),
        [
            # Standard segment
            (
                "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav",
                datetime(2026, 3, 26, 1, 35, 0, tzinfo=UTC),
            ),
            # Segment with 0s and max seq
            (
                "2026-01-01T00-00-00Z_30s_1a2b3c4d_99999999.wav",
                datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            ),
            # Maximum limits format and leap year timing
            (
                "2028-02-29T23-59-59Z_15s_ffffffff_00000000.wav",
                datetime(2028, 2, 29, 23, 59, 59, tzinfo=UTC),
            ),
        ],
    )
    def test_valid_filenames(self, filename: str, expected_ts: datetime) -> None:
        """Parse ISO-timestamp correctly from various valid v0.6 component combinations."""
        ts = indexer.parse_timestamp(filename)
        assert ts == expected_ts

    def test_invalid_format_raises(self) -> None:
        """Non-matching filename raises ValueError."""
        with pytest.raises(ValueError):
            indexer.parse_timestamp("not_a_timestamp.wav")

    def test_parse_timestamp_warns_on_1970(self) -> None:
        """A timestamp with a pre-NTP year logs a warning but parses successfully."""
        from unittest.mock import patch

        with patch("silvasonic.processor.indexer.log.warning") as mock_warn:
            ts = indexer.parse_timestamp("1970-01-01T00-01-05Z_10s_1a2b3c4d_00000000.wav")
            assert ts.year == 1970
            mock_warn.assert_called_once()
            assert mock_warn.call_args[1]["year"] == 1970


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
        _create_wav(dev_dir / "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav")

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


@pytest.mark.unit
class TestResolveRawPathFallback:
    """Verify resolve_raw_path when 'processed' is absent from path."""

    def test_path_without_processed_unchanged(self) -> None:
        """Path without 'processed' component is returned as-is."""
        original = Path("/data/recorder/mic-01/data/raw/seg.wav")
        result = indexer.resolve_raw_path(original)
        assert result == original


@pytest.mark.unit
class TestIndexRecordings:
    """Verify index_recordings full insert path and error handling."""

    async def test_new_file_indexed_and_committed(self, tmp_path: Path) -> None:
        """New WAV file is inserted into DB and session is committed."""
        dev_dir = tmp_path / "mic-01" / "data" / "processed"
        dev_dir.mkdir(parents=True)
        wav = dev_dir / "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav"
        _create_wav(wav, duration_s=1.0, sample_rate=48000)

        # Also create the corresponding raw file
        raw_dir = tmp_path / "mic-01" / "data" / "raw"
        raw_dir.mkdir(parents=True)
        _create_wav(raw_dir / "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav", duration_s=1.0)

        # Mock session: idempotency → not indexed, device → exists, INSERT
        select_result = MagicMock()
        select_result.fetchone.return_value = None

        device_result = MagicMock()
        device_result.fetchone.return_value = ("mic-01",)  # Device exists, returns name

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[select_result, device_result, AsyncMock()])
        session.commit = AsyncMock()

        result = await indexer.index_recordings(session, tmp_path)
        assert result.new == 1
        assert result.skipped == 0
        assert result.errors == 0
        session.commit.assert_called_once()

    async def test_extraction_error_counted(self, tmp_path: Path) -> None:
        """Corrupt WAV file triggers error counter, not crash."""
        dev_dir = tmp_path / "mic-01" / "data" / "processed"
        dev_dir.mkdir(parents=True)
        corrupt = dev_dir / "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav"
        corrupt.write_bytes(b"NOT_A_WAV")

        # Mock session: idempotency → not indexed, device → exists
        # extract_metadata raises before INSERT
        select_result = MagicMock()
        select_result.fetchone.return_value = None

        device_result = MagicMock()
        device_result.fetchone.return_value = ("mic-01",)  # Device exists, returns name

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[select_result, device_result])
        session.commit = AsyncMock()

        result = await indexer.index_recordings(session, tmp_path)
        assert result.errors == 1
        assert result.new == 0
        assert len(result.error_details) == 1
        # commit should NOT be called (no successful inserts)
        session.commit.assert_not_called()
        # rollback MUST be called to reset the aborted transaction state
        session.rollback.assert_called_once()


@pytest.mark.unit
class TestDeviceExistenceCheck:
    """Verify Indexer checks device existence before INSERT."""

    async def test_skips_file_when_device_not_registered(self, tmp_path: Path) -> None:
        """File for unregistered device is skipped, not errored.

        When the Controller hasn't registered a device yet, the Indexer
        must skip the file (not crash with FK violation) and count it
        as skipped — it's a transient timing issue, not a data problem.
        """
        dev_dir = tmp_path / "mic-01" / "data" / "processed"
        dev_dir.mkdir(parents=True)
        _create_wav(dev_dir / "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav")

        # Mock: idempotency → not indexed
        idempotency_result = MagicMock()
        idempotency_result.fetchone.return_value = None

        # Mock: device check → NOT in DB
        device_result = MagicMock()
        device_result.fetchone.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[idempotency_result, device_result])
        session.commit = AsyncMock()

        result = await indexer.index_recordings(session, tmp_path)

        assert result.skipped == 1
        assert result.new == 0
        assert result.errors == 0
        session.commit.assert_not_called()


@pytest.mark.unit
class TestSkipFiles:
    """Verify error blacklist prevents re-processing of failed files."""

    async def test_skipped_file_not_reprocessed(self, tmp_path: Path) -> None:
        """Files in errored_files set are immediately skipped without DB queries.

        Prevents the Indexer from retrying the same broken file every
        polling cycle, which would flood the logs with identical errors.
        """
        dev_dir = tmp_path / "mic-01" / "data" / "processed"
        dev_dir.mkdir(parents=True)
        _create_wav(dev_dir / "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav")

        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()

        result = await indexer.index_recordings(
            session,
            tmp_path,
            errored_files={"mic-01/data/processed/2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav"},
        )

        assert result.skipped == 1
        assert result.new == 0
        assert result.errors == 0
        # No DB interaction at all for errored files
        session.execute.assert_not_called()
        session.commit.assert_not_called()


# ===================================================================
# Realistic Production Naming (Name-Mismatch)
# ===================================================================


@pytest.mark.unit
class TestRealisticProductionNaming:
    """Verify Indexer handles realistic workspace dir vs. device name.

    In production, the Controller creates workspace directories using
    profile-slug-based naming (e.g., "ultramic-384-evo-034f"), but
    stores devices.name as the stable_device_id (e.g., "0869-0389-00000000034F").
    The device's workspace_name column bridges the lookup.

    The Indexer extracts workspace_dir from the filesystem and queries
    ``SELECT name FROM devices WHERE workspace_name = :ws_name``.

    See: Log Analysis Report 2026-03-30 — Name-Mismatch (workspace_name vs device.name).
    """

    async def test_indexes_file_with_production_workspace_name(self, tmp_path: Path) -> None:
        """Indexer must index files when workspace dir differs from device.name.

        Setup mirrors the exact production scenario:
        - Workspace dir: "ultramic-384-evo-034f" (from container_spec)
        - devices.name in DB: "0869-0389-00000000034F" (from device_scanner)
        - devices.workspace_name in DB: "ultramic-384-evo-034f" (from reconciler)
        - The DB contains the device, with workspace_name matching the dir.
        """
        workspace_dir = "ultramic-384-evo-034f"  # From build_recorder_spec
        db_device_name = "0869-0389-00000000034F"  # From upsert_device

        # Create a WAV file in the production-style workspace
        dev_dir = tmp_path / workspace_dir / "data" / "processed"
        dev_dir.mkdir(parents=True)
        raw_dir = tmp_path / workspace_dir / "data" / "raw"
        raw_dir.mkdir(parents=True)
        _create_wav(dev_dir / "2026-03-30T14-52-47Z_15s_1a2b3c4d_00000000.wav")
        _create_wav(raw_dir / "2026-03-30T14-52-47Z_15s_1a2b3c4d_00000000.wav")

        # Mock DB responses:
        # 1. Idempotency check → not indexed yet
        idempotency_result = MagicMock()
        idempotency_result.fetchone.return_value = None

        # 2. Device lookup by workspace_name → returns the stable device name
        device_result = MagicMock()
        device_result.fetchone.return_value = (db_device_name,)

        # 3. INSERT
        insert_result = AsyncMock()

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[idempotency_result, device_result, insert_result])
        session.commit = AsyncMock()

        result = await indexer.index_recordings(session, tmp_path)

        # In the FIXED code: result.new should be 1
        assert result.new == 1, (
            f"Indexer failed to index recording from workspace dir "
            f"'{workspace_dir}'. devices.name in DB is '{db_device_name}'. "
            f"Got: new={result.new}, skipped={result.skipped}, errors={result.errors}"
        )


# ===================================================================
# Raw-Only Devices Invisible to Indexer
# ===================================================================


@pytest.mark.unit
class TestRawOnlyDeviceDiscovery:
    """Verify that scan_workspace discovers devices with only raw/ data.

    Devices with ``processed_enabled: false`` (Rode NT-USB, Generic USB,
    Behringer, Focusrite — 4 of 8 profiles) only produce files in
    ``data/raw/``, not ``data/processed/``.

    See: Gemini Log Analysis Report 2026-03-30 — RAW-Only device discovery.
    """

    def test_scan_workspace_discovers_raw_only_device(self, tmp_path: Path) -> None:
        """scan_workspace must find WAV files from raw-only devices.

        A device like the Rode NT-USB (48kHz native, no downsampling)
        has processed_enabled=False. Its workspace only contains
        data/raw/*.wav — no data/processed/ directory at all.
        """
        # Setup: raw-only workspace (no processed/ dir)
        raw_dir = tmp_path / "rode-nt-usb-p3d6" / "data" / "raw"
        raw_dir.mkdir(parents=True)
        _create_wav(raw_dir / "2026-03-30T14-52-47Z_15s_1a2b3c4d_00000000.wav")
        _create_wav(raw_dir / "2026-03-30T14-53-02Z_15s_1a2b3c4d_00000000.wav")

        # No processed/ directory exists — processed_enabled=False

        result = indexer.scan_workspace(tmp_path)

        assert len(result) >= 1, (
            "scan_workspace() found 0 files for raw-only device. "
            "Devices with processed_enabled=False are invisible to the indexer. "
            "4 of 8 profiles are affected (rode_nt_usb, generic_usb, "
            "behringer_uphoria, focusrite_scarlett)."
        )

    def test_scan_workspace_deduplicates_dual_stream(self, tmp_path: Path) -> None:
        """When both raw and processed exist, only processed is returned.

        This prevents double-indexing for dual-stream devices.
        """
        device_dir = tmp_path / "ultramic-384-evo-034f"
        processed_dir = device_dir / "data" / "processed"
        raw_dir = device_dir / "data" / "raw"
        processed_dir.mkdir(parents=True)
        raw_dir.mkdir(parents=True)

        filename = "2026-03-30T14-52-47Z_15s_1a2b3c4d_00000000.wav"
        _create_wav(processed_dir / filename)
        _create_wav(raw_dir / filename)

        result = indexer.scan_workspace(tmp_path)

        assert len(result) == 1
        assert "processed" in str(result[0])
