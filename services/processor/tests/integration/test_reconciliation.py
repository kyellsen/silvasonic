"""Integration tests for the Reconciliation Audit module.

Tests the startup audit against a real station database
(SQLite). Seeds recordings, manipulates the filesystem, and
verifies the audit correctly marks orphaned rows.
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
from silvasonic.processor import reconciliation
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker


def _create_wav(path: Path) -> None:
    """Create a minimal valid WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(b"\x00\x00" * 48000)


@pytest.mark.integration
class TestReconciliationIntegration:
    """Verify Reconciliation Audit end-to-end with a real station database."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch: pytest.MonkeyPatch, station_db: Path) -> None:
        """Point the code under test at the test database."""
        _get_engine.cache_clear()
        _get_session_factory.cache_clear()
        monkeypatch.setenv("SILVASONIC_DB_PATH", str(station_db))

    async def test_orphaned_rows_healed(self, station_db: Path, tmp_path: Path) -> None:
        """Seed DB with local_deleted=false, remove files → audit marks local_deleted=true."""
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Seed device and recording
        async with factory() as session:
            await session.execute(
                text("""
                    INSERT INTO devices (name, serial_number, model, config)
                    VALUES ('mic-01', 'SN-001', 'Test', '{}')
                    ON CONFLICT (name) DO NOTHING
                """)
            )
            await session.execute(
                text("""
                    INSERT INTO recordings (
                        time, sensor_id, file_raw, file_processed,
                        duration, sample_rate, filesize_raw, filesize_processed
                    ) VALUES (
                        1767225600000000, 'mic-01',  -- 2026-01-01T00:00:00Z in epoch µs
                        'mic-01/data/raw/gone.wav', 'mic-01/data/processed/gone.wav',
                        10.0, 48000, 960000, 960000
                    )
                """)
            )
            await session.commit()

        # File does NOT exist on disk → audit should mark as deleted
        async with factory() as session:
            count = await reconciliation.run_audit(session, tmp_path)

        assert count == 1

        # Verify local_deleted is now true
        async with factory() as session:
            result = await session.execute(text("SELECT local_deleted FROM recordings LIMIT 1"))
            assert bool(result.scalar()) is True

        await engine.dispose()

    async def test_valid_rows_preserved(self, station_db: Path, tmp_path: Path) -> None:
        """Seed DB with local_deleted=false, files exist → no changes."""
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Create the files on disk
        _create_wav(tmp_path / "mic-01" / "data" / "raw" / "exists.wav")
        _create_wav(tmp_path / "mic-01" / "data" / "processed" / "exists.wav")

        # Seed device and recording
        async with factory() as session:
            await session.execute(
                text("""
                    INSERT INTO devices (name, serial_number, model, config)
                    VALUES ('mic-01', 'SN-001', 'Test', '{}')
                    ON CONFLICT (name) DO NOTHING
                """)
            )
            await session.execute(
                text("""
                    INSERT INTO recordings (
                        time, sensor_id, file_raw, file_processed,
                        duration, sample_rate, filesize_raw, filesize_processed
                    ) VALUES (
                        1767225600000000, 'mic-01',  -- 2026-01-01T00:00:00Z in epoch µs
                        'mic-01/data/raw/exists.wav', 'mic-01/data/processed/exists.wav',
                        10.0, 48000, 960000, 960000
                    )
                """)
            )
            await session.commit()

        # File EXISTS on disk → audit should not change anything
        async with factory() as session:
            count = await reconciliation.run_audit(session, tmp_path)

        assert count == 0

        # Verify local_deleted is still false
        async with factory() as session:
            result = await session.execute(text("SELECT local_deleted FROM recordings LIMIT 1"))
            assert bool(result.scalar()) is False

        await engine.dispose()
