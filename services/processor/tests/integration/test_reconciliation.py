"""Integration tests for the Reconciliation Audit module.

Tests the startup audit against a real PostgreSQL database
(Testcontainer). Seeds recordings, manipulates the filesystem, and
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
    """Verify Reconciliation Audit end-to-end with real PostgreSQL."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch: pytest.MonkeyPatch, station_db: Path) -> None:
        """Inject testcontainer DB credentials into environment."""
        _get_engine.cache_clear()
        _get_session_factory.cache_clear()
        monkeypatch.setenv("SILVASONIC_DB_PATH", str(station_db))

    async def test_orphaned_rows_healed(self, station_db: Path, tmp_path: Path) -> None:
        """Undeleted row whose file is gone → audit sets deleted_at, reason 'missing'."""
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Seed microphone and recording
        async with factory() as session:
            await session.execute(
                text("""
                    INSERT INTO microphones (hardware_id, name, serial_number, model, hardware)
                    VALUES ('mic-01', 'Test', 'SN-001', 'Test', '{}')
                    ON CONFLICT (hardware_id) DO NOTHING
                """)
            )
            await session.execute(
                text("""
                    INSERT INTO recordings (
                        started_at, microphone_id, raw_path, processed_path,
                        duration_s, sample_rate_hz, raw_size_bytes, processed_size_bytes
                    ) VALUES (
                        1767225600000000,  -- 2026-01-01T00:00:00Z in epoch µs
                        (SELECT id FROM microphones WHERE hardware_id = 'mic-01'),
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

        # Verify deleted_at and deletion_reason are now set
        async with factory() as session:
            result = await session.execute(
                text("SELECT deleted_at IS NOT NULL, deletion_reason FROM recordings LIMIT 1")
            )
            assert tuple(result.one()) == (True, "missing")

        await engine.dispose()

    async def test_valid_rows_preserved(self, station_db: Path, tmp_path: Path) -> None:
        """Undeleted row whose files exist → no changes."""
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Create the files on disk
        _create_wav(tmp_path / "mic-01" / "data" / "raw" / "exists.wav")
        _create_wav(tmp_path / "mic-01" / "data" / "processed" / "exists.wav")

        # Seed microphone and recording
        async with factory() as session:
            await session.execute(
                text("""
                    INSERT INTO microphones (hardware_id, name, serial_number, model, hardware)
                    VALUES ('mic-01', 'Test', 'SN-001', 'Test', '{}')
                    ON CONFLICT (hardware_id) DO NOTHING
                """)
            )
            await session.execute(
                text("""
                    INSERT INTO recordings (
                        started_at, microphone_id, raw_path, processed_path,
                        duration_s, sample_rate_hz, raw_size_bytes, processed_size_bytes
                    ) VALUES (
                        1767225600000000,  -- 2026-01-01T00:00:00Z in epoch µs
                        (SELECT id FROM microphones WHERE hardware_id = 'mic-01'),
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

        # Verify deleted_at and deletion_reason are still unset
        async with factory() as session:
            result = await session.execute(
                text("SELECT deleted_at, deletion_reason FROM recordings LIMIT 1")
            )
            assert tuple(result.one()) == (None, None)

        await engine.dispose()
