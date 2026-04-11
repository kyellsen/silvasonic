"""Integration tests for the Janitor module.

Uses the shared ``postgres_container`` Testcontainer fixture (conftest.py)
to verify the full Janitor cycle against a real database:
- Correct SQL query execution per retention mode
- Soft-delete pattern (physical file removal + DB flag update)
- Cloud-Sync-Fallback: cloud sync disabled → skip ``uploaded`` condition
- Batch-size enforcement against real DB
- Mode-specific file preservation guarantees
"""

from __future__ import annotations

import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from silvasonic.core.database.session import _get_engine, _get_session_factory
from silvasonic.processor.janitor import (
    RetentionMode,
    run_cleanup,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

pytestmark = [pytest.mark.integration]

# NOTE(testing.md §5.3 exception): get_disk_usage patches host-level I/O
# (shutil.disk_usage) which cannot be controlled in CI containers.
# This is NOT a database mock and therefore not forbidden by the
# integration test rules.  See: docs/development/testing.md §5.1.


def _build_async_url(container: PostgresContainer) -> str:
    """Build an asyncpg connection URL from a testcontainer."""
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    return f"postgresql+asyncpg://silvasonic:silvasonic@{host}:{port}/silvasonic_test"


def _create_wav(path: Path, *, duration_s: float = 1.0, sample_rate: int = 48000) -> None:
    """Create a minimal valid WAV file for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(duration_s * sample_rate)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)


async def _seed_device(factory: async_sessionmaker[Any], name: str) -> None:
    """Insert a test device row (FK constraint for recordings)."""
    async with factory() as session:
        await session.execute(
            text("""
                INSERT INTO devices (name, serial_number, model, config)
                VALUES (:name, :sn, 'TestMic', '{}')
                ON CONFLICT (name) DO NOTHING
            """),
            {"name": name, "sn": f"SN-{name}"},
        )
        await session.commit()


async def _seed_recording(
    factory: async_sessionmaker[Any],
    *,
    sensor_id: str,
    file_raw: str,
    file_processed: str,
    uploaded: bool = False,
    analysis_state_sql: str = "'{}'::jsonb",
    local_deleted: bool = False,
    time: datetime,
) -> int:
    """Insert a recording row and return its ID."""
    async with factory() as session:
        result = await session.execute(
            text(f"""
                INSERT INTO recordings (
                    time, sensor_id, file_raw, file_processed,
                    duration, sample_rate, filesize_raw, filesize_processed,
                    uploaded, local_deleted, analysis_state
                ) VALUES (
                    :time, :sensor_id, :file_raw, :file_processed,
                    3.0, 48000, 288000, 288000,
                    :uploaded, :local_deleted, {analysis_state_sql}
                )
                RETURNING id
            """),
            {
                "time": time,
                "sensor_id": sensor_id,
                "file_raw": file_raw,
                "file_processed": file_processed,
                "uploaded": uploaded,
                "local_deleted": local_deleted,
            },
        )
        row = result.fetchone()
        assert row is not None
        await session.commit()
        return int(row[0])


async def _enable_upload_config(factory: async_sessionmaker[Any]) -> None:
    """Simulate Cloud Sync enabled in system_config."""
    async with factory() as session:
        await session.execute(
            text("""
                INSERT INTO system_config (key, value)
                VALUES ('cloud_sync', '{"enabled": true}'::jsonb)
                ON CONFLICT (key) DO UPDATE SET value = '{"enabled": true}'::jsonb
            """)
        )
        await session.commit()


async def _disable_upload_config(factory: async_sessionmaker[Any]) -> None:
    """Simulate Cloud Sync disabled in system_config."""
    async with factory() as session:
        await session.execute(
            text("""
                INSERT INTO system_config (key, value)
                VALUES ('cloud_sync', '{"enabled": false}'::jsonb)
                ON CONFLICT (key) DO UPDATE SET value = '{"enabled": false}'::jsonb
            """)
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestJanitorIntegration:
    """Janitor integration tests with real PostgreSQL (shared postgres_container)."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch: pytest.MonkeyPatch, postgres_container: Any) -> None:
        """Inject testcontainer DB credentials into environment."""
        _get_engine.cache_clear()
        _get_session_factory.cache_clear()
        monkeypatch.setenv("SILVASONIC_DB_HOST", postgres_container.get_container_host_ip())
        monkeypatch.setenv("SILVASONIC_DB_PORT", str(postgres_container.get_exposed_port(5432)))
        monkeypatch.setenv("POSTGRES_USER", "silvasonic")
        monkeypatch.setenv("POSTGRES_PASSWORD", "silvasonic")
        monkeypatch.setenv("POSTGRES_DB", "silvasonic_test")

    async def test_housekeeping_deletes_correct_files(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """75% disk + Cloud Sync → only uploaded+analyzed files deleted."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        await _seed_device(factory, "hk-mic")
        await _enable_upload_config(factory)

        # File 1: uploaded + fully analyzed → should be deleted
        del_proc = tmp_path / "hk-mic" / "data" / "processed" / "uploaded.wav"
        del_raw = tmp_path / "hk-mic" / "data" / "raw" / "uploaded.wav"
        _create_wav(del_proc)
        _create_wav(del_raw)
        del_id = await _seed_recording(
            factory,
            sensor_id="hk-mic",
            file_raw="hk-mic/data/raw/uploaded.wav",
            file_processed="hk-mic/data/processed/uploaded.wav",
            uploaded=True,
            analysis_state_sql='\'{"birdnet": "true"}\'::jsonb',
            time=datetime(2026, 1, 1, tzinfo=UTC),
        )

        # File 2: not uploaded → should be preserved
        kept_proc = tmp_path / "hk-mic" / "data" / "processed" / "kept.wav"
        kept_raw = tmp_path / "hk-mic" / "data" / "raw" / "kept.wav"
        _create_wav(kept_proc)
        _create_wav(kept_raw)
        kept_id = await _seed_recording(
            factory,
            sensor_id="hk-mic",
            file_raw="hk-mic/data/raw/kept.wav",
            file_processed="hk-mic/data/processed/kept.wav",
            uploaded=False,
            time=datetime(2026, 1, 2, tzinfo=UTC),
        )

        from silvasonic.core.schemas.system_config import ProcessorSettings

        settings = ProcessorSettings()
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.HOUSEKEEPING
        assert result.files_deleted == 1
        assert result.cloud_sync_fallback is False
        assert not del_proc.exists()
        assert kept_proc.exists()

        # Verify DB: soft-delete flag
        async with factory() as session:
            row_del = await session.execute(
                text("SELECT local_deleted FROM recordings WHERE id = :id"), {"id": del_id}
            )
            assert row_del.scalar() is True
            row_kept = await session.execute(
                text("SELECT local_deleted FROM recordings WHERE id = :id"), {"id": kept_id}
            )
            assert row_kept.scalar() is False

        await engine.dispose()

    async def test_housekeeping_cloud_sync_fallback(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """75% disk + NO Cloud Sync → 'uploaded' condition skipped, fallback active."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        await _disable_upload_config(factory)
        await _seed_device(factory, "fb-mic")

        # File: not uploaded, but fully analyzed → should be deleted in fallback
        proc = tmp_path / "fb-mic" / "data" / "processed" / "analyzed.wav"
        raw = tmp_path / "fb-mic" / "data" / "raw" / "analyzed.wav"
        _create_wav(proc)
        _create_wav(raw)
        rec_id = await _seed_recording(
            factory,
            sensor_id="fb-mic",
            file_raw="fb-mic/data/raw/analyzed.wav",
            file_processed="fb-mic/data/processed/analyzed.wav",
            uploaded=False,
            analysis_state_sql='\'{"birdnet": "true"}\'::jsonb',
            time=datetime(2026, 1, 1, tzinfo=UTC),
        )

        from silvasonic.core.schemas.system_config import ProcessorSettings

        settings = ProcessorSettings()
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.HOUSEKEEPING
        assert result.cloud_sync_fallback is True
        assert result.files_deleted == 1
        assert not proc.exists()

        # Verify soft-delete
        async with factory() as session:
            row = await session.execute(
                text("SELECT local_deleted FROM recordings WHERE id = :id"), {"id": rec_id}
            )
            assert row.scalar() is True

        await engine.dispose()

    async def test_defensive_deletes_uploaded_only(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """85% disk + Cloud Sync → uploaded files deleted even without analysis."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        await _seed_device(factory, "def-mic")
        await _enable_upload_config(factory)

        proc = tmp_path / "def-mic" / "data" / "processed" / "uploaded_no_analysis.wav"
        raw = tmp_path / "def-mic" / "data" / "raw" / "uploaded_no_analysis.wav"
        _create_wav(proc)
        _create_wav(raw)
        rec_id = await _seed_recording(
            factory,
            sensor_id="def-mic",
            file_raw="def-mic/data/raw/uploaded_no_analysis.wav",
            file_processed="def-mic/data/processed/uploaded_no_analysis.wav",
            uploaded=True,
            time=datetime(2026, 2, 1, tzinfo=UTC),
        )

        from silvasonic.core.schemas.system_config import ProcessorSettings

        settings = ProcessorSettings()
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=85.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.DEFENSIVE
        assert result.files_deleted >= 1
        assert not proc.exists()

        # Verify soft-delete in DB
        async with factory() as session:
            row = await session.execute(
                text("SELECT local_deleted FROM recordings WHERE id = :id"), {"id": rec_id}
            )
            assert row.scalar() is True

        await engine.dispose()

    async def test_defensive_cloud_sync_fallback(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """85% disk + NO Cloud Sync → all non-deleted recordings eligible."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        await _disable_upload_config(factory)
        await _seed_device(factory, "dfb-mic")

        proc = tmp_path / "dfb-mic" / "data" / "processed" / "not_uploaded.wav"
        raw = tmp_path / "dfb-mic" / "data" / "raw" / "not_uploaded.wav"
        _create_wav(proc)
        _create_wav(raw)
        rec_id = await _seed_recording(
            factory,
            sensor_id="dfb-mic",
            file_raw="dfb-mic/data/raw/not_uploaded.wav",
            file_processed="dfb-mic/data/processed/not_uploaded.wav",
            uploaded=False,
            time=datetime(2026, 3, 1, tzinfo=UTC),
        )

        from silvasonic.core.schemas.system_config import ProcessorSettings

        settings = ProcessorSettings()
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=85.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.DEFENSIVE
        assert result.cloud_sync_fallback is True
        assert result.files_deleted == 1
        assert not proc.exists()

        # Verify soft-delete
        async with factory() as session:
            row = await session.execute(
                text("SELECT local_deleted FROM recordings WHERE id = :id"), {"id": rec_id}
            )
            assert row.scalar() is True

        await engine.dispose()

    async def test_panic_deletes_oldest(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """95% disk → oldest file deleted first, newer file preserved (batch_size=1)."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        await _seed_device(factory, "panic-mic")

        old_proc = tmp_path / "panic-mic" / "data" / "processed" / "old.wav"
        old_raw = tmp_path / "panic-mic" / "data" / "raw" / "old.wav"
        _create_wav(old_proc)
        _create_wav(old_raw)
        old_id = await _seed_recording(
            factory,
            sensor_id="panic-mic",
            file_raw="panic-mic/data/raw/old.wav",
            file_processed="panic-mic/data/processed/old.wav",
            uploaded=False,
            time=datetime(2025, 1, 1, tzinfo=UTC),
        )

        new_proc = tmp_path / "panic-mic" / "data" / "processed" / "new.wav"
        new_raw = tmp_path / "panic-mic" / "data" / "raw" / "new.wav"
        _create_wav(new_proc)
        _create_wav(new_raw)
        new_id = await _seed_recording(
            factory,
            sensor_id="panic-mic",
            file_raw="panic-mic/data/raw/new.wav",
            file_processed="panic-mic/data/processed/new.wav",
            uploaded=False,
            time=datetime(2026, 12, 1, tzinfo=UTC),
        )

        from silvasonic.core.schemas.system_config import ProcessorSettings

        settings = ProcessorSettings(janitor_batch_size=1)
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=95.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.PANIC
        assert result.files_deleted == 1
        assert not old_proc.exists()  # Oldest deleted first
        assert new_proc.exists()  # Newer preserved (batch_size=1)

        # Verify soft-delete flags
        async with factory() as session:
            row_old = await session.execute(
                text("SELECT local_deleted FROM recordings WHERE id = :id"), {"id": old_id}
            )
            assert row_old.scalar() is True
            row_new = await session.execute(
                text("SELECT local_deleted FROM recordings WHERE id = :id"), {"id": new_id}
            )
            assert row_new.scalar() is False

        await engine.dispose()

    async def test_batch_size_limits_deletions(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """Panic mode with batch_size=2 only deletes 2 of 5 files."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        await _seed_device(factory, "batch-mic")

        for i in range(5):
            proc = tmp_path / "batch-mic" / "data" / "processed" / f"seg_{i:02d}.wav"
            raw = tmp_path / "batch-mic" / "data" / "raw" / f"seg_{i:02d}.wav"
            _create_wav(proc)
            _create_wav(raw)
            await _seed_recording(
                factory,
                sensor_id="batch-mic",
                file_raw=f"batch-mic/data/raw/seg_{i:02d}.wav",
                file_processed=f"batch-mic/data/processed/seg_{i:02d}.wav",
                uploaded=False,
                time=datetime(2026, 1, i + 1, tzinfo=UTC),
            )

        from silvasonic.core.schemas.system_config import ProcessorSettings

        settings = ProcessorSettings(janitor_batch_size=2)
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=95.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.PANIC
        assert result.files_deleted == 2

        # Verify exactly 2 rows soft-deleted, 3 remaining
        async with factory() as session:
            deleted_count = await session.execute(
                text("""
                    SELECT COUNT(*) FROM recordings
                    WHERE local_deleted = true AND sensor_id = 'batch-mic'
                """)
            )
            assert deleted_count.scalar() == 2
            remaining_count = await session.execute(
                text("""
                    SELECT COUNT(*) FROM recordings
                    WHERE local_deleted = false AND sensor_id = 'batch-mic'
                """)
            )
            assert remaining_count.scalar() == 3

        await engine.dispose()

    async def test_panic_filesystem_fallback(self, tmp_path: Path) -> None:
        """Filesystem mtime-based cleanup when DB is unavailable."""
        import os

        from silvasonic.processor.janitor import panic_filesystem_fallback

        sensor_dir = tmp_path / "fb-mic" / "data" / "processed"
        sensor_dir.mkdir(parents=True)

        for i, name in enumerate(["old.wav", "newer.wav"]):
            f = sensor_dir / name
            f.write_bytes(b"\x00" * 100)
            os.utime(f, (1000 + i * 1000, 1000 + i * 1000))

        deleted = panic_filesystem_fallback(tmp_path, batch_size=1)
        assert deleted == 1
        assert not (sensor_dir / "old.wav").exists()
        assert (sensor_dir / "newer.wav").exists()

    async def test_already_deleted_not_redeleted(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """Rows with local_deleted=true are not picked up for deletion."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        await _seed_device(factory, "skip-mic")

        await _seed_recording(
            factory,
            sensor_id="skip-mic",
            file_raw="skip-mic/data/raw/already_gone.wav",
            file_processed="skip-mic/data/processed/already_gone.wav",
            uploaded=False,
            local_deleted=True,
            time=datetime(2025, 1, 1, tzinfo=UTC),
        )

        from silvasonic.core.schemas.system_config import ProcessorSettings

        settings = ProcessorSettings()
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=95.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.PANIC
        assert result.files_deleted == 0

        await engine.dispose()
