"""Integration tests for the Indexer module.

Tests WAV indexing against a real PostgreSQL database
(Testcontainer). Creates synthetic WAV files, runs the Indexer, and
verifies ``recordings`` rows in the database.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest
from silvasonic.core.database.session import (
    _get_engine,
    _get_session_factory,
    create_station_engine,
)
from silvasonic.processor import indexer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _create_wav(
    path: Path, *, duration_s: float = 1.0, sample_rate_hz: int = 48000, channels: int = 1
) -> None:
    """Create a minimal valid WAV file for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(duration_s * sample_rate_hz)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate_hz)
        wf.writeframes(b"\x00\x00" * channels * n_frames)


def _setup_workspace(base: Path, workspace: str = "mic-01", count: int = 2) -> list[Path]:
    """Create a mock workspace with WAV files and returns created paths."""
    created = []
    for i in range(count):
        for stream in ("processed", "raw"):
            d = base / workspace / "data" / stream
            d.mkdir(parents=True, exist_ok=True)
            wav = d / f"2026-01-01T0{i}-00-00Z_10s_1a2b3c4d_0000{i:04d}.wav"
            _create_wav(wav, duration_s=10.0)
            if stream == "processed":
                created.append(wav)
    return created


async def _seed_microphone(
    session: AsyncSession, hardware_id: str = "mic-01", *, workspace_name: str | None = None
) -> None:
    """Insert a test microphone into the microphones table.

    Args:
        session: Active async DB session.
        hardware_id: Stable Device ID of the microphone.
        workspace_name: Workspace directory name. Defaults to ``hardware_id``
            for simple test fixtures where dir name == hardware_id.
    """
    ws = workspace_name if workspace_name is not None else hardware_id
    await session.execute(
        text("""
            INSERT INTO microphones (hardware_id, name, serial_number, model, hardware,
                                     workspace_name)
            VALUES (:hw, 'TestMic', :sn, 'TestMic', '{}', :ws)
            ON CONFLICT (hardware_id) DO NOTHING
        """),
        {"hw": hardware_id, "sn": f"SN-{hardware_id}", "ws": ws},
    )
    await session.commit()


_HARDWARE_IDS_SQL = """
    SELECT m.hardware_id FROM recordings r
    JOIN microphones m ON m.id = r.microphone_id
    ORDER BY m.hardware_id
"""


@pytest.mark.integration
class TestIndexerIntegration:
    """Verify Indexer integration with real PostgreSQL."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch: pytest.MonkeyPatch, station_db: Path) -> None:
        """Inject testcontainer DB credentials into environment."""
        _get_engine.cache_clear()
        _get_session_factory.cache_clear()
        monkeypatch.setenv("SILVASONIC_DB_PATH", str(station_db))

    async def test_new_wav_indexed(self, station_db: Path, tmp_path: Path) -> None:
        """Synthetic WAVs in workspace → Indexer picks up → verify recordings rows."""
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            await _seed_microphone(session, "mic-01")

        _setup_workspace(tmp_path, "mic-01", count=2)

        async with factory() as session:
            result = await indexer.index_recordings(session, tmp_path)

        assert result.new == 2
        assert result.skipped == 0
        assert result.errors == 0

        # Verify rows in DB
        async with factory() as session:
            rows = await session.execute(text("SELECT COUNT(*) FROM recordings"))
            count = rows.scalar()
            assert count == 2

        await engine.dispose()

    async def test_idempotent_reindex(self, station_db: Path, tmp_path: Path) -> None:
        """Running Indexer twice on same files → no duplicate rows."""
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            await _seed_microphone(session, "mic-01")

        _setup_workspace(tmp_path, "mic-01", count=1)

        # First run
        async with factory() as session:
            r1 = await indexer.index_recordings(session, tmp_path)
        assert r1.new == 1

        # Second run — same files
        async with factory() as session:
            r2 = await indexer.index_recordings(session, tmp_path)
        assert r2.new == 0
        assert r2.skipped == 1

        # Verify only 1 row
        async with factory() as session:
            rows = await session.execute(text("SELECT COUNT(*) FROM recordings"))
            assert rows.scalar() == 1

        await engine.dispose()

    async def test_raw_only_reindex_and_path_indexes(
        self, station_db: Path, tmp_path: Path
    ) -> None:
        """Raw-only files are found again by raw_path; lookups use the path indexes."""
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            await _seed_microphone(session, "rode-01")

        _create_wav(
            tmp_path / "rode-01" / "data" / "raw" / "2026-01-01T05-00-00Z_10s_1a2b3c4d_00000000.wav"
        )

        async with factory() as session:
            r1 = await indexer.index_recordings(session, tmp_path)
        async with factory() as session:
            r2 = await indexer.index_recordings(session, tmp_path)

        assert (r1.new, r2.new, r2.skipped) == (1, 0, 1)

        async with factory() as session:
            rows = await session.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'index' AND tbl_name = 'recordings'"
                )
            )
            names = {row[0] for row in rows}
        assert {"ix_recordings_raw_path", "ix_recordings_processed_path"} <= names

        await engine.dispose()

    async def test_unsynced_marker_is_stored(self, station_db: Path, tmp_path: Path) -> None:
        """A segment named before NTP sync is not clock_synced; a plain one is."""
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            await _seed_microphone(session, "rode-01")

        raw_dir = tmp_path / "rode-01" / "data" / "raw"
        _create_wav(raw_dir / "2026-01-01T05-00-00Z_10s_1a2b3c4d_00000000_unsynced.wav")
        _create_wav(raw_dir / "2026-01-01T05-00-10Z_10s_1a2b3c4d_00000001.wav")

        async with factory() as session:
            result = await indexer.index_recordings(session, tmp_path)
        assert result.new == 2

        async with factory() as session:
            rows = await session.execute(
                text("SELECT started_at, clock_synced FROM recordings ORDER BY started_at")
            )
            flags = [row[1] for row in rows]
        assert flags == [False, True]

        await engine.dispose()

    async def test_multiple_microphones_indexed(self, station_db: Path, tmp_path: Path) -> None:
        """Files from two workspace directories → correct microphone_id per row."""
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            await _seed_microphone(session, "mic-01")
            await _seed_microphone(session, "mic-02")

        _setup_workspace(tmp_path, "mic-01", count=1)
        _setup_workspace(tmp_path, "mic-02", count=1)

        async with factory() as session:
            result = await indexer.index_recordings(session, tmp_path)

        assert result.new == 2

        # Verify microphone_ids resolve to the right microphones
        async with factory() as session:
            rows = await session.execute(text(_HARDWARE_IDS_SQL))
            hardware_ids = [r[0] for r in rows.fetchall()]
            assert hardware_ids == ["mic-01", "mic-02"]

        await engine.dispose()

    async def test_unregistered_microphone_skipped_not_errored(
        self, station_db: Path, tmp_path: Path
    ) -> None:
        """Indexer skips files for unregistered microphones instead of FK error.

        This is the exact scenario from the production bug: WAV files exist on
        disk for a microphone that has not yet been enrolled by the Controller.
        With the microphone existence check, the Indexer must:
        1. Skip the file (count as skipped, not error).
        2. Never attempt the INSERT (no FK violation).
        3. Leave zero rows in the recordings table.
        """
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Setup: WAV exists but microphone "ghost-mic" is NOT in the microphones table
        _setup_workspace(tmp_path, "ghost-mic", count=1)

        async with factory() as session:
            result = await indexer.index_recordings(session, tmp_path)

        # Must count as skipped (transient timing issue), not error
        assert result.skipped == 1, f"Expected 1 skipped, got {result.skipped}"
        assert result.errors == 0, f"Expected 0 errors, got {result.errors}"
        assert result.new == 0

        # Session must still be usable (no aborted transaction)
        async with factory() as session:
            rows = await session.execute(text("SELECT COUNT(*) FROM recordings"))
            assert rows.scalar() == 0, "No recordings should exist"

        await engine.dispose()

    async def test_unregistered_microphone_does_not_block_valid_recordings(
        self, station_db: Path, tmp_path: Path
    ) -> None:
        """Unregistered microphone is skipped; valid microphone recordings still indexed.

        Simulates a mixed workspace where one microphone directory has no matching
        DB entry (skipped) and another does. The Indexer must:
        1. Skip the unregistered microphone's file.
        2. Successfully INSERT the recording for the known microphone.
        3. Report correct skipped and new counts.
        """
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Seed only "good-mic", NOT "bad-mic"
        async with factory() as session:
            await _seed_microphone(session, "good-mic")

        # Create WAV files for both microphones
        _setup_workspace(tmp_path, "bad-mic", count=1)
        _setup_workspace(tmp_path, "good-mic", count=1)

        async with factory() as session:
            result = await indexer.index_recordings(session, tmp_path)

        assert result.skipped == 1, f"Expected 1 skipped (bad-mic), got {result.skipped}"
        assert result.new == 1, f"Expected 1 new (good-mic), got {result.new}"
        assert result.errors == 0, f"Expected 0 errors, got {result.errors}"

        # Verify only the valid recording is in the DB
        async with factory() as session:
            rows = await session.execute(text("SELECT COUNT(*) FROM recordings"))
            count = rows.scalar()
            assert count == 1, f"Expected 1 recording, got {count}"

            hw_row = await session.execute(text(_HARDWARE_IDS_SQL))
            hardware_id = hw_row.scalar()
            assert hardware_id == "good-mic", f"Expected 'good-mic', got '{hardware_id}'"

        await engine.dispose()

    async def test_errored_files_prevents_reprocessing(
        self, station_db: Path, tmp_path: Path
    ) -> None:
        """Files in errored_files are not retried, preventing log flood.

        Simulates the corrupt-WAV scenario: a corrupt WAV causes an error on the
        first indexing cycle. On the next cycle, the caller passes the error
        file in errored_files so it is immediately skipped without any DB query.
        """
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Seed microphone so the lookup passes (we want to test corrupt WAV path)
        async with factory() as session:
            await _seed_microphone(session, "mic-01")

        # Create a corrupt WAV file
        corrupt_dir = tmp_path / "mic-01" / "data" / "processed"
        corrupt_dir.mkdir(parents=True, exist_ok=True)
        corrupt_wav = corrupt_dir / "2026-01-01T00-00-00Z_10s_1a2b3c4d_00000000.wav"
        corrupt_wav.write_bytes(b"NOT_A_WAV")

        # First call: corrupt WAV causes extract_metadata error
        async with factory() as session:
            r1 = await indexer.index_recordings(session, tmp_path)
        assert r1.errors == 1
        assert len(r1.error_details) == 1

        # Second call: pass error_details as errored_files → no retry
        async with factory() as session:
            r2 = await indexer.index_recordings(
                session, tmp_path, errored_files=set(r1.error_details)
            )
        assert r2.skipped == 1, f"Expected 1 skipped, got {r2.skipped}"
        assert r2.errors == 0, f"Expected 0 errors, got {r2.errors}"

        await engine.dispose()

    async def test_native_sample_rate_from_raw_file(self, station_db: Path, tmp_path: Path) -> None:
        """sample_rate_hz and channels come from the raw file, not the indexed one.

        Dual stream: raw at 384 kHz stereo, processed at 48 kHz mono → 384000 / 2.
        Raw file missing: the processed file's values are the fallback.
        """
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            await _seed_microphone(session, "ultra-01")

        ws = tmp_path / "ultra-01" / "data"
        both = "2026-01-01T05-00-00Z_1s_1a2b3c4d_00000000.wav"
        processed_only = "2026-01-01T05-00-01Z_1s_1a2b3c4d_00000001.wav"
        _create_wav(ws / "raw" / both, sample_rate_hz=384000, channels=2)
        _create_wav(ws / "processed" / both, sample_rate_hz=48000)
        _create_wav(ws / "processed" / processed_only, sample_rate_hz=48000)

        async with factory() as session:
            result = await indexer.index_recordings(session, tmp_path)
        assert result.new == 2

        async with factory() as session:
            rows = await session.execute(
                text(
                    "SELECT sample_rate_hz, channels, raw_size_bytes > 0 "
                    "FROM recordings ORDER BY started_at"
                )
            )
            values = [tuple(r) for r in rows.fetchall()]
        assert values == [(384000, 2, True), (48000, 1, False)]

        await engine.dispose()
