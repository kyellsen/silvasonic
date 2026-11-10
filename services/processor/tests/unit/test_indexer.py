"""Unit tests for the Indexer module.

Tests WAV metadata extraction, path parsing, timestamp parsing,
idempotency, and workspace scanning — all without a real DB.
"""

from __future__ import annotations

import uuid
import wave
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from silvasonic.processor import indexer

MIC_ID = uuid.UUID("0193f1c2-7b3a-7c4e-9d55-0a1b2c3d4e5f")


def _create_wav(
    path: Path, *, duration_s: float = 1.0, sample_rate_hz: int = 48000, channels: int = 1
) -> None:
    """Create a minimal valid WAV file for testing."""
    n_frames = int(duration_s * sample_rate_hz)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate_hz)
        # Write silence (zeros)
        wf.writeframes(b"\x00\x00" * channels * n_frames)


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

    def test_multiple_workspaces_discovered(self, tmp_path: Path) -> None:
        """Files from multiple microphone directories are all discovered."""
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
class TestClockMarker:
    """Segments named with an unsynchronised clock carry a suffix (Issue 002)."""

    def test_marked_segment_parses_and_flags(self) -> None:
        """The suffix leaves the timestamp intact and sets the flag."""
        name = "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000_unsynced.wav"
        assert indexer.parse_timestamp(name) == datetime(2026, 3, 26, 1, 35, 0, tzinfo=UTC)
        assert indexer.is_clock_synced(name) is False

    def test_plain_segment_is_synced(self) -> None:
        """Names without the suffix, the normal case, are trusted."""
        assert indexer.is_clock_synced("2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav") is True

    def test_unknown_suffix_rejected(self) -> None:
        """Only the documented suffix is accepted."""
        with pytest.raises(ValueError):
            indexer.is_clock_synced("2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000_x.wav")

    async def test_marker_reaches_the_insert(self, tmp_path: Path) -> None:
        """The indexer stores the flag with the recording."""
        dev_dir = tmp_path / "mic-01" / "data" / "processed"
        dev_dir.mkdir(parents=True)
        _create_wav(dev_dir / "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000_unsynced.wav")

        microphone_result = MagicMock()
        microphone_result.fetchone.return_value = (MIC_ID,)
        exists_result = MagicMock()
        exists_result.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[exists_result, microphone_result, MagicMock()])

        result = await indexer.index_recordings(session, tmp_path)

        assert result.new == 1
        insert_params = session.execute.await_args_list[-1].args[0].compile().params
        assert insert_params["clock_synced"] is False
        assert insert_params["microphone_id"] == MIC_ID


@pytest.mark.unit
class TestExtractMetadata:
    """Verify WAV metadata extraction via soundfile."""

    def test_wav_metadata_extraction(self, tmp_path: Path) -> None:
        """Extracted metadata matches the synthetic WAV properties."""
        wav = tmp_path / "test.wav"
        _create_wav(wav, duration_s=2.0, sample_rate_hz=48000, channels=2)

        meta = indexer.extract_metadata(wav)
        assert meta.sample_rate_hz == 48000
        assert meta.channels == 2
        assert abs(meta.duration_s - 2.0) < 0.01
        assert meta.size_bytes > 0


@pytest.mark.unit
class TestResolveWorkspaceName:
    """Verify workspace name extraction from path structure."""

    def test_workspace_name_from_path(self, tmp_path: Path) -> None:
        """Path .../recorder/ultramic-01/data/processed/seg.wav → 'ultramic-01'."""
        wav = tmp_path / "ultramic-01" / "data" / "processed" / "seg.wav"
        workspace_name = indexer.resolve_workspace_name(wav, tmp_path)
        assert workspace_name == "ultramic-01"


@pytest.mark.unit
class TestNativeSampleRate:
    """sample_rate_hz and channels are the microphone's native values."""

    async def _insert_params(self, tmp_path: Path) -> dict[str, object]:
        session = AsyncMock()
        exists_result = MagicMock()
        exists_result.all.return_value = []
        microphone_result = MagicMock()
        microphone_result.fetchone.return_value = (MIC_ID,)
        session.execute = AsyncMock(side_effect=[exists_result, microphone_result, MagicMock()])
        result = await indexer.index_recordings(session, tmp_path)
        assert result.new == 1
        return session.execute.await_args_list[-1].args[0].compile().params

    async def test_dual_stream_stores_raw_rate(self, tmp_path: Path) -> None:
        """Raw at 384 kHz stereo, processed at 48 kHz mono → 384000 Hz, 2 channels."""
        name = "2026-03-26T01-35-00Z_1s_1a2b3c4d_00000000.wav"
        for stream in ("raw", "processed"):
            (tmp_path / "mic-01" / "data" / stream).mkdir(parents=True)
        _create_wav(tmp_path / "mic-01/data/raw" / name, sample_rate_hz=384000, channels=2)
        _create_wav(tmp_path / "mic-01/data/processed" / name, sample_rate_hz=48000)

        params = await self._insert_params(tmp_path)

        assert params["sample_rate_hz"] == 384000
        assert params["channels"] == 2
        assert params["processed_path"] == f"mic-01/data/processed/{name}"
        assert params["raw_path"] == f"mic-01/data/raw/{name}"

    async def test_missing_raw_falls_back_to_processed(self, tmp_path: Path) -> None:
        """Without the raw file the processed file's header is the fallback."""
        name = "2026-03-26T01-35-00Z_1s_1a2b3c4d_00000000.wav"
        (tmp_path / "mic-01" / "data" / "processed").mkdir(parents=True)
        _create_wav(tmp_path / "mic-01/data/processed" / name, sample_rate_hz=48000)

        params = await self._insert_params(tmp_path)

        assert params["sample_rate_hz"] == 48000
        assert params["channels"] == 1
        assert params["raw_size_bytes"] == 0

    async def test_raw_only_stores_raw_rate(self, tmp_path: Path) -> None:
        """A raw-only microphone stores its raw file's rate."""
        name = "2026-03-26T01-35-00Z_1s_1a2b3c4d_00000000.wav"
        (tmp_path / "mic-01" / "data" / "raw").mkdir(parents=True)
        _create_wav(tmp_path / "mic-01/data/raw" / name, sample_rate_hz=96000)

        params = await self._insert_params(tmp_path)

        assert params["sample_rate_hz"] == 96000
        assert params["processed_path"] is None


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
        mock_result.all.return_value = [
            (
                "mic-01/data/raw/2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav",
                "mic-01/data/processed/2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav",
            )
        ]

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
class TestMicrophoneExistenceCheck:
    """Verify Indexer checks microphone existence before INSERT."""

    async def test_skips_file_when_microphone_not_registered(self, tmp_path: Path) -> None:
        """File for unregistered microphone is skipped, not errored.

        When the Controller hasn't registered a microphone yet, the Indexer
        must skip the file (not crash with FK violation) and count it
        as skipped — it's a transient timing issue, not a data problem.
        """
        dev_dir = tmp_path / "mic-01" / "data" / "processed"
        dev_dir.mkdir(parents=True)
        _create_wav(dev_dir / "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav")

        # Mock: idempotency → not indexed
        idempotency_result = MagicMock()
        idempotency_result.all.return_value = []

        # Mock: microphone check → NOT in DB
        microphone_result = MagicMock()
        microphone_result.fetchone.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[idempotency_result, microphone_result])
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
# Cost per cycle (known-file cache, batched existence check)
# ===================================================================


def _exists_result(rows: list[tuple[str, str | None]]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _microphone_result(microphone_id: uuid.UUID | None) -> MagicMock:
    result = MagicMock()
    result.fetchone.return_value = (microphone_id,) if microphone_id is not None else None
    return result


@pytest.mark.unit
class TestCyclesStayCheap:
    """A cycle queries the DB only for files it has not seen before."""

    async def test_known_files_cost_no_query(self, tmp_path: Path) -> None:
        """Once indexed, a file is skipped without touching the DB."""
        dev_dir = tmp_path / "mic-01" / "data" / "processed"
        dev_dir.mkdir(parents=True)
        _create_wav(dev_dir / "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav")

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[_exists_result([]), _microphone_result(MIC_ID), MagicMock()]
        )
        known: set[str] = set()

        first = await indexer.index_recordings(session, tmp_path, known_files=known)
        assert first.new == 1
        assert known == {"mic-01/data/processed/2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav"}

        session.execute.reset_mock()
        second = await indexer.index_recordings(session, tmp_path, known_files=known)

        assert second.new == 0
        assert second.skipped == 1
        session.execute.assert_not_called()

    async def test_existing_files_checked_in_one_query(self, tmp_path: Path) -> None:
        """Many unseen files that the DB already holds cost a single query."""
        dev_dir = tmp_path / "mic-01" / "data" / "processed"
        dev_dir.mkdir(parents=True)
        rows: list[tuple[str, str | None]] = []
        for seq in range(50):
            name = f"2026-03-26T01-35-{seq:02d}Z_10s_1a2b3c4d_{seq:08d}.wav"
            _create_wav(dev_dir / name)
            rows.append((f"mic-01/data/raw/{name}", f"mic-01/data/processed/{name}"))

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_exists_result(rows))
        known: set[str] = set()

        result = await indexer.index_recordings(session, tmp_path, known_files=known)

        assert result.skipped == 50
        assert session.execute.await_count == 1
        assert len(known) == 50

    async def test_deleted_files_leave_the_cache(self, tmp_path: Path) -> None:
        """Files the Janitor removed are dropped, so the cache stays bounded."""
        known = {"mic-01/data/processed/gone.wav"}
        session = AsyncMock()

        await indexer.index_recordings(session, tmp_path, known_files=known)

        assert known == set()

    async def test_failing_file_keeps_earlier_inserts(self, tmp_path: Path) -> None:
        """Each insert commits on its own; a later failure rolls back only itself."""
        dev_dir = tmp_path / "mic-01" / "data" / "processed"
        dev_dir.mkdir(parents=True)
        good = "2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav"
        bad = "2026-03-26T01-35-10Z_10s_1a2b3c4d_00000001.wav"
        _create_wav(dev_dir / good)
        (dev_dir / bad).write_bytes(b"corrupt")

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[_exists_result([]), _microphone_result(MIC_ID), MagicMock()]
        )
        known: set[str] = set()

        result = await indexer.index_recordings(session, tmp_path, known_files=known)

        assert result.new == 1
        assert result.errors == 1
        session.commit.assert_awaited_once()
        # Two releases of the read lock before file I/O (ADR-0037), then the
        # failing file's own rollback, which comes last.
        assert session.rollback.await_count == 3
        assert session.method_calls[-1] == call.rollback()
        assert known == {f"mic-01/data/processed/{good}"}


# ===================================================================
# Realistic Production Naming (Name-Mismatch)
# ===================================================================


@pytest.mark.unit
class TestRealisticProductionNaming:
    """Verify Indexer handles realistic workspace dir vs. microphone identity.

    In production, the Controller creates workspace directories using
    profile-slug-based naming (e.g., "ultramic-384-evo-034f"), while the
    microphone's key is a UUID and its hardware_id the Stable Device ID
    (e.g., "0869-0389-00000000034F").  The microphone's workspace_name
    column bridges the lookup.

    The Indexer extracts workspace_dir from the filesystem and queries
    ``SELECT id FROM microphones WHERE workspace_name = :ws_name``.

    See: Log Analysis Report 2026-03-30 — Name-Mismatch (workspace_name vs hardware_id).
    """

    async def test_indexes_file_with_production_workspace_name(self, tmp_path: Path) -> None:
        """Indexer must index files when workspace dir differs from hardware_id.

        Setup mirrors the exact production scenario:
        - Workspace dir: "ultramic-384-evo-034f" (from container_spec)
        - microphones.hardware_id in DB: "0869-0389-00000000034F" (from device_scanner)
        - microphones.workspace_name in DB: "ultramic-384-evo-034f" (from reconciler)
        - The DB contains the microphone, with workspace_name matching the dir.
        """
        workspace_dir = "ultramic-384-evo-034f"  # From build_recorder_spec

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
        idempotency_result.all.return_value = []

        # 2. Microphone lookup by workspace_name → returns the microphone id
        microphone_result = MagicMock()
        microphone_result.fetchone.return_value = (MIC_ID,)

        # 3. INSERT
        insert_result = AsyncMock()

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[idempotency_result, microphone_result, insert_result]
        )
        session.commit = AsyncMock()

        result = await indexer.index_recordings(session, tmp_path)

        # In the FIXED code: result.new should be 1
        assert result.new == 1, (
            f"Indexer failed to index recording from workspace dir "
            f"'{workspace_dir}'. "
            f"Got: new={result.new}, skipped={result.skipped}, errors={result.errors}"
        )


# ===================================================================
# Raw-Only Microphones Invisible to Indexer
# ===================================================================


@pytest.mark.unit
class TestRawOnlyMicrophoneDiscovery:
    """Verify that scan_workspace discovers microphones with only raw/ data.

    Devices with ``processed_enabled: false`` (Rode NT-USB, Generic USB,
    Behringer, Focusrite — 4 of 8 profiles) only produce files in
    ``data/raw/``, not ``data/processed/``.

    See: Gemini Log Analysis Report 2026-03-30 — RAW-Only microphone discovery.
    """

    def test_scan_workspace_discovers_raw_only_microphone(self, tmp_path: Path) -> None:
        """scan_workspace must find WAV files from raw-only microphones.

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
            "scan_workspace() found 0 files for raw-only microphone. "
            "Devices with processed_enabled=False are invisible to the indexer. "
            "4 of 8 profiles are affected (rode_nt_usb, generic_usb, "
            "behringer_uphoria, focusrite_scarlett)."
        )

    def test_scan_workspace_deduplicates_dual_stream(self, tmp_path: Path) -> None:
        """When both raw and processed exist, only processed is returned.

        This prevents double-indexing for dual-stream microphones.
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
