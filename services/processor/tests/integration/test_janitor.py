"""Integration tests for the Janitor module.

Uses the shared ``postgres_container`` Testcontainer fixture (conftest.py)
to verify the full Janitor cycle against a real database:
- Correct SQL query execution per retention mode
- Soft-delete pattern (physical file removal + ``deleted_at``/``deletion_reason``)
- Cloud-Sync-Fallback: cloud_sync module off → skip ``uploaded_at`` condition
- Batch-size enforcement against real DB
- Mode-specific file preservation guarantees
"""

from __future__ import annotations

import uuid
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from silvasonic.core.database.session import _get_engine, _get_session_factory
from silvasonic.core.schemas.settings import StorageSettings
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


def _create_wav(path: Path, *, duration_s: float = 1.0, sample_rate_hz: int = 48000) -> None:
    """Create a minimal valid WAV file for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(duration_s * sample_rate_hz)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate_hz)
        wf.writeframes(b"\x00\x00" * n_frames)


#: When the seeded recordings were uploaded (or deleted).
UPLOADED_AT = datetime(2026, 6, 1, tzinfo=UTC)

#: ``analysis_state`` of a recording BirdNET has finished (schemas/analysis.py).
ANALYSED_SQL = (
    """'{"birdnet": {"state": "done", "reason": null, """
    """"finished_at": "2026-01-01T00:00:00Z", "detection_count": 0}}'::jsonb"""
)


async def _seed_microphone(factory: async_sessionmaker[Any], hardware_id: str) -> None:
    """Insert a test microphone row (FK constraint for recordings)."""
    async with factory() as session:
        await session.execute(
            text("""
                INSERT INTO microphones (hardware_id, name, serial_number, model, hardware)
                VALUES (:hw, 'TestMic', :sn, 'TestMic', '{}')
                ON CONFLICT (hardware_id) DO NOTHING
            """),
            {"hw": hardware_id, "sn": f"SN-{hardware_id}"},
        )
        await session.commit()


async def _seed_recording(
    factory: async_sessionmaker[Any],
    *,
    hardware_id: str,
    raw_path: str,
    processed_path: str,
    uploaded_at: datetime | None = None,
    analysis_state_sql: str = "'{}'::jsonb",
    deleted_at: datetime | None = None,
    started_at: datetime,
) -> uuid.UUID:
    """Insert a recording row and return its ID."""
    async with factory() as session:
        result = await session.execute(
            text(f"""
                INSERT INTO recordings (
                    started_at, microphone_id, raw_path, processed_path,
                    duration_s, sample_rate_hz, raw_size_bytes, processed_size_bytes,
                    uploaded_at, deleted_at, analysis_state
                ) VALUES (
                    :started_at,
                    (SELECT id FROM microphones WHERE hardware_id = :hardware_id),
                    :raw_path, :processed_path,
                    3.0, 48000, 288000, 288000,
                    :uploaded_at, :deleted_at,
                    {analysis_state_sql}
                )
                RETURNING id
            """),
            {
                "started_at": started_at,
                "hardware_id": hardware_id,
                "raw_path": raw_path,
                "processed_path": processed_path,
                "uploaded_at": uploaded_at,
                "deleted_at": deleted_at,
            },
        )
        row = result.fetchone()
        assert row is not None
        await session.commit()
        return row[0]


async def _deletion(factory: async_sessionmaker[Any], rec_id: uuid.UUID) -> str | None:
    """Return the recording's ``deletion_reason`` (``None`` = not deleted).

    Also asserts that ``deleted_at`` and ``deletion_reason`` are set together.
    """
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT deleted_at, deletion_reason FROM recordings WHERE id = :id"),
                {"id": rec_id},
            )
        ).one()
    assert (row[0] is None) == (row[1] is None)
    return row[1]


async def _seed_detection(
    factory: async_sessionmaker[Any],
    *,
    recording_id: uuid.UUID,
    analyzer: str = "birdnet",
    clip_path: str = "clips/test.wav",
) -> None:
    """Insert a detection row referencing a recording."""
    async with factory() as session:
        await session.execute(
            text("""
                INSERT INTO detections (
                    started_at, ended_at, recording_id, analyzer, label, confidence,
                    clip_path, details
                ) VALUES (
                    now(),
                    now() + interval '3 seconds',
                    :recording_id,
                    :analyzer,
                    'TestLabel',
                    0.9,
                    :clip_path,
                    '{}'::jsonb
                )
            """),
            {
                "recording_id": recording_id,
                "analyzer": analyzer,
                "clip_path": clip_path,
            },
        )
        await session.commit()


async def _enable_upload_config(factory: async_sessionmaker[Any]) -> None:
    """Simulate the cloud_sync module switched on."""
    async with factory() as session:
        await session.execute(
            text("""
                INSERT INTO modules (id, enabled) VALUES ('cloud_sync', true)
                ON CONFLICT (id) DO UPDATE SET enabled = true
            """)
        )
        await session.commit()


async def _disable_upload_config(factory: async_sessionmaker[Any]) -> None:
    """Simulate the cloud_sync module switched off."""
    async with factory() as session:
        await session.execute(
            text("""
                INSERT INTO modules (id, enabled) VALUES ('cloud_sync', false)
                ON CONFLICT (id) DO UPDATE SET enabled = false
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

        await _seed_microphone(factory, "hk-mic")
        await _enable_upload_config(factory)

        # File 1: uploaded + fully analyzed → should be deleted
        del_proc = tmp_path / "hk-mic" / "data" / "processed" / "uploaded.wav"
        del_raw = tmp_path / "hk-mic" / "data" / "raw" / "uploaded.wav"
        _create_wav(del_proc)
        _create_wav(del_raw)
        del_id = await _seed_recording(
            factory,
            hardware_id="hk-mic",
            raw_path="hk-mic/data/raw/uploaded.wav",
            processed_path="hk-mic/data/processed/uploaded.wav",
            uploaded_at=UPLOADED_AT,
            analysis_state_sql=ANALYSED_SQL,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        # File 2: not uploaded → should be preserved
        kept_proc = tmp_path / "hk-mic" / "data" / "processed" / "kept.wav"
        kept_raw = tmp_path / "hk-mic" / "data" / "raw" / "kept.wav"
        _create_wav(kept_proc)
        _create_wav(kept_raw)
        kept_id = await _seed_recording(
            factory,
            hardware_id="hk-mic",
            raw_path="hk-mic/data/raw/kept.wav",
            processed_path="hk-mic/data/processed/kept.wav",
            started_at=datetime(2026, 1, 2, tzinfo=UTC),
        )

        settings = StorageSettings()
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.HOUSEKEEPING
        assert result.recordings_deleted == 1
        assert result.cloud_sync_fallback is False
        assert not del_proc.exists()
        assert kept_proc.exists()

        # Verify DB: soft-delete flag
        async with factory() as session:
            row_del = await session.execute(
                text("SELECT deleted_at IS NOT NULL FROM recordings WHERE id = :id"), {"id": del_id}
            )
            assert row_del.scalar() is True
            row_kept = await session.execute(
                text("SELECT deleted_at IS NOT NULL FROM recordings WHERE id = :id"),
                {"id": kept_id},
            )
            assert row_kept.scalar() is False

        # The Janitor records why: retention
        assert await _deletion(factory, del_id) == "retention"
        assert await _deletion(factory, kept_id) is None

        await engine.dispose()

    async def test_housekeeping_skips_failed_analysis(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """A recording whose analysis failed is not 'fully analysed' for housekeeping."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        await _seed_microphone(factory, "hkf-mic")
        await _disable_upload_config(factory)

        proc = tmp_path / "hkf-mic" / "data" / "processed" / "failed.wav"
        _create_wav(proc)
        rec_id = await _seed_recording(
            factory,
            hardware_id="hkf-mic",
            raw_path="hkf-mic/data/raw/failed.wav",
            processed_path="hkf-mic/data/processed/failed.wav",
            analysis_state_sql=(
                """'{"birdnet": {"state": "failed", "reason": "error", """
                """"finished_at": "2026-01-01T00:00:00Z", "detection_count": null}}'::jsonb"""
            ),
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, StorageSettings())

        assert result.recordings_deleted == 0
        assert proc.exists()
        assert await _deletion(factory, rec_id) is None

        await engine.dispose()

    async def test_housekeeping_deletes_worker_clips(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """75% disk + Cloud Sync → uploaded files deleted AND associated clips removed."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        await _seed_microphone(factory, "hk2-mic")
        await _enable_upload_config(factory)

        # 1. Provide recording
        del_proc = tmp_path / "hk2-mic" / "data" / "processed" / "uploaded.wav"
        del_raw = tmp_path / "hk2-mic" / "data" / "raw" / "uploaded.wav"
        _create_wav(del_proc)
        _create_wav(del_raw)

        # 2. Provide the associated worker clip
        # tmp_path represents the workspace_root (/data in container)
        # Therefore: tmp_path / "birdnet" / "clips" / "mock.wav"
        worker = "birdnet"
        clip_path = "clips/mock.wav"
        physical_clip = tmp_path / worker / clip_path
        _create_wav(physical_clip)

        rec_id = await _seed_recording(
            factory,
            hardware_id="hk2-mic",
            raw_path="hk2-mic/data/raw/uploaded.wav",
            processed_path="hk2-mic/data/processed/uploaded.wav",
            uploaded_at=UPLOADED_AT,
            analysis_state_sql=ANALYSED_SQL,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        # 3. Associate clip with recording
        await _seed_detection(
            factory,
            recording_id=rec_id,
            analyzer=worker,
            clip_path=clip_path,
        )

        settings = StorageSettings()
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0):
            async with factory() as session:
                # We need to simulate the execution environment of `run_cleanup`
                # which gets the recordings directory (tmp_path / "recorder")
                # Wait, the recordings_dir passed here is just `tmp_path`.
                # If we pass `tmp_path` as recordings_dir, then `recordings_dir.parent`
                # will be the parent of `tmp_path`, which breaks `delete_worker_clips`.
                # So we simulate the directory layout better:
                # `workspace_root` = tmp_path
                # `recordings_dir` = tmp_path / "recorder"
                pass  # Done outside the context manager to avoid deep nesting

        # Create recordings dir properly inside tmp_path for accurate relative paths
        recordings_dir = tmp_path / "recorder"

        # Re-create files inside recordings_dir as expected by delete_files logic
        # which appends `hk2-mic/data...` to `recordings_dir`
        del_proc = recordings_dir / "hk2-mic" / "data" / "processed" / "uploaded.wav"
        del_raw = recordings_dir / "hk2-mic" / "data" / "raw" / "uploaded.wav"
        _create_wav(del_proc)
        _create_wav(del_raw)

        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0):
            async with factory() as session:
                result = await run_cleanup(session, recordings_dir, settings)

        assert result.mode == RetentionMode.HOUSEKEEPING
        assert result.recordings_deleted == 1

        # Assert underlying files are gone
        assert not del_proc.exists()
        assert not del_raw.exists()

        # Assert clip is physically gone
        assert not physical_clip.exists()

        # Assert DB nullification
        async with factory() as session:
            row_clip = await session.execute(
                text("SELECT clip_path FROM detections WHERE recording_id = :id"), {"id": rec_id}
            )
            assert row_clip.scalar() is None

        await engine.dispose()

    async def test_housekeeping_cloud_sync_fallback(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """75% disk + NO Cloud Sync → 'uploaded' condition skipped, fallback active."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        await _disable_upload_config(factory)
        await _seed_microphone(factory, "fb-mic")

        # File: not uploaded, but fully analyzed → should be deleted in fallback
        proc = tmp_path / "fb-mic" / "data" / "processed" / "analyzed.wav"
        raw = tmp_path / "fb-mic" / "data" / "raw" / "analyzed.wav"
        _create_wav(proc)
        _create_wav(raw)
        rec_id = await _seed_recording(
            factory,
            hardware_id="fb-mic",
            raw_path="fb-mic/data/raw/analyzed.wav",
            processed_path="fb-mic/data/processed/analyzed.wav",
            analysis_state_sql=ANALYSED_SQL,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        settings = StorageSettings()
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.HOUSEKEEPING
        assert result.cloud_sync_fallback is True
        assert result.recordings_deleted == 1
        assert not proc.exists()

        # Verify soft-delete
        async with factory() as session:
            row = await session.execute(
                text("SELECT deleted_at IS NOT NULL FROM recordings WHERE id = :id"), {"id": rec_id}
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

        await _seed_microphone(factory, "def-mic")
        await _enable_upload_config(factory)

        proc = tmp_path / "def-mic" / "data" / "processed" / "uploaded_no_analysis.wav"
        raw = tmp_path / "def-mic" / "data" / "raw" / "uploaded_no_analysis.wav"
        _create_wav(proc)
        _create_wav(raw)
        rec_id = await _seed_recording(
            factory,
            hardware_id="def-mic",
            raw_path="def-mic/data/raw/uploaded_no_analysis.wav",
            processed_path="def-mic/data/processed/uploaded_no_analysis.wav",
            uploaded_at=UPLOADED_AT,
            started_at=datetime(2026, 2, 1, tzinfo=UTC),
        )

        settings = StorageSettings()
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=85.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.DEFENSIVE
        assert result.recordings_deleted >= 1
        assert not proc.exists()

        # Verify soft-delete in DB
        async with factory() as session:
            row = await session.execute(
                text("SELECT deleted_at IS NOT NULL FROM recordings WHERE id = :id"), {"id": rec_id}
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
        await _seed_microphone(factory, "dfb-mic")

        proc = tmp_path / "dfb-mic" / "data" / "processed" / "not_uploaded.wav"
        raw = tmp_path / "dfb-mic" / "data" / "raw" / "not_uploaded.wav"
        _create_wav(proc)
        _create_wav(raw)
        rec_id = await _seed_recording(
            factory,
            hardware_id="dfb-mic",
            raw_path="dfb-mic/data/raw/not_uploaded.wav",
            processed_path="dfb-mic/data/processed/not_uploaded.wav",
            started_at=datetime(2026, 3, 1, tzinfo=UTC),
        )

        settings = StorageSettings()
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=85.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.DEFENSIVE
        assert result.cloud_sync_fallback is True
        assert result.recordings_deleted == 1
        assert not proc.exists()

        # Verify soft-delete
        async with factory() as session:
            row = await session.execute(
                text("SELECT deleted_at IS NOT NULL FROM recordings WHERE id = :id"), {"id": rec_id}
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

        await _seed_microphone(factory, "panic-mic")

        old_proc = tmp_path / "panic-mic" / "data" / "processed" / "old.wav"
        old_raw = tmp_path / "panic-mic" / "data" / "raw" / "old.wav"
        _create_wav(old_proc)
        _create_wav(old_raw)
        old_id = await _seed_recording(
            factory,
            hardware_id="panic-mic",
            raw_path="panic-mic/data/raw/old.wav",
            processed_path="panic-mic/data/processed/old.wav",
            started_at=datetime(2025, 1, 1, tzinfo=UTC),
        )

        new_proc = tmp_path / "panic-mic" / "data" / "processed" / "new.wav"
        new_raw = tmp_path / "panic-mic" / "data" / "raw" / "new.wav"
        _create_wav(new_proc)
        _create_wav(new_raw)
        new_id = await _seed_recording(
            factory,
            hardware_id="panic-mic",
            raw_path="panic-mic/data/raw/new.wav",
            processed_path="panic-mic/data/processed/new.wav",
            started_at=datetime(2026, 12, 1, tzinfo=UTC),
        )

        settings = StorageSettings(cleanup_batch_files=1)
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=95.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.PANIC
        assert result.recordings_deleted == 1
        assert not old_proc.exists()  # Oldest deleted first
        assert new_proc.exists()  # Newer preserved (batch_size=1)

        # Verify soft-delete flags
        async with factory() as session:
            row_old = await session.execute(
                text("SELECT deleted_at IS NOT NULL FROM recordings WHERE id = :id"), {"id": old_id}
            )
            assert row_old.scalar() is True
            row_new = await session.execute(
                text("SELECT deleted_at IS NOT NULL FROM recordings WHERE id = :id"), {"id": new_id}
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

        await _seed_microphone(factory, "batch-mic")

        for i in range(5):
            proc = tmp_path / "batch-mic" / "data" / "processed" / f"seg_{i:02d}.wav"
            raw = tmp_path / "batch-mic" / "data" / "raw" / f"seg_{i:02d}.wav"
            _create_wav(proc)
            _create_wav(raw)
            await _seed_recording(
                factory,
                hardware_id="batch-mic",
                raw_path=f"batch-mic/data/raw/seg_{i:02d}.wav",
                processed_path=f"batch-mic/data/processed/seg_{i:02d}.wav",
                started_at=datetime(2026, 1, i + 1, tzinfo=UTC),
            )

        settings = StorageSettings(cleanup_batch_files=2)
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=95.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.PANIC
        assert result.recordings_deleted == 2

        # Verify exactly 2 rows soft-deleted, 3 remaining
        async with factory() as session:
            deleted_count = await session.execute(
                text("""
                    SELECT COUNT(*) FROM recordings
                    WHERE deleted_at IS NOT NULL AND microphone_id =
                        (SELECT id FROM microphones WHERE hardware_id = 'batch-mic')
                """)
            )
            assert deleted_count.scalar() == 2
            remaining_count = await session.execute(
                text("""
                    SELECT COUNT(*) FROM recordings
                    WHERE deleted_at IS NULL AND microphone_id =
                        (SELECT id FROM microphones WHERE hardware_id = 'batch-mic')
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

        deleted = await panic_filesystem_fallback(tmp_path, batch_size=1)
        assert deleted == 1
        assert not (sensor_dir / "old.wav").exists()
        assert (sensor_dir / "newer.wav").exists()

    async def test_already_deleted_not_redeleted(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """Rows with deleted_at set are not picked up for deletion."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        await _seed_microphone(factory, "skip-mic")

        await _seed_recording(
            factory,
            hardware_id="skip-mic",
            raw_path="skip-mic/data/raw/already_gone.wav",
            processed_path="skip-mic/data/processed/already_gone.wav",
            deleted_at=UPLOADED_AT,
            started_at=datetime(2025, 1, 1, tzinfo=UTC),
        )

        settings = StorageSettings()
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=95.0):
            async with factory() as session:
                result = await run_cleanup(session, tmp_path, settings)

        assert result.mode == RetentionMode.PANIC
        assert result.recordings_deleted == 0

        await engine.dispose()

    async def test_partial_deletion_failure_does_not_abort_soft_delete(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """Partial deletion failure ensures DB strictly limits updates to successful unlinks."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        await _seed_microphone(factory, "partial-mic")
        await _enable_upload_config(factory)

        recordings_dir = tmp_path / "recorder"

        # 1. Provide recording (raw & processed)
        proc = recordings_dir / "partial-mic" / "data" / "processed" / "uploaded.wav"
        raw = recordings_dir / "partial-mic" / "data" / "raw" / "uploaded.wav"
        _create_wav(proc)
        _create_wav(raw)

        # 2. Provide TWO associated worker clips
        worker = "birdnet"
        clip_path_success = "clips/success.wav"
        clip_path_fail = "clips/fail.wav"

        physical_clip_success = tmp_path / worker / clip_path_success
        _create_wav(physical_clip_success)

        physical_clip_fail = tmp_path / worker / clip_path_fail
        _create_wav(physical_clip_fail)

        rec_id = await _seed_recording(
            factory,
            hardware_id="partial-mic",
            raw_path="partial-mic/data/raw/uploaded.wav",
            processed_path="partial-mic/data/processed/uploaded.wav",
            uploaded_at=UPLOADED_AT,
            analysis_state_sql=ANALYSED_SQL,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        await _seed_detection(
            factory, recording_id=rec_id, analyzer=worker, clip_path=clip_path_success
        )
        await _seed_detection(
            factory, recording_id=rec_id, analyzer=worker, clip_path=clip_path_fail
        )

        original_unlink = Path.unlink

        def _mock_unlink(self_path: Path, *args: Any, **kwargs: Any) -> None:
            if "fail.wav" in str(self_path):
                raise PermissionError("Mock failure for fail.wav")
            original_unlink(self_path, *args, **kwargs)

        settings = StorageSettings()

        with (
            patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0),
            patch.object(Path, "unlink", side_effect=_mock_unlink, autospec=True),
        ):
            async with factory() as session:
                result = await run_cleanup(session, recordings_dir, settings)

        assert result.mode == RetentionMode.HOUSEKEEPING
        assert result.recordings_deleted == 1
        assert result.errors == 1

        # Assert successful clip is gone
        assert not physical_clip_success.exists()
        # Assert failed clip remains
        assert physical_clip_fail.exists()

        # Assert DB strictly limited NULL updates to successful clips
        async with factory() as session:
            rows = await session.execute(
                text("SELECT clip_path FROM detections WHERE recording_id = :id"), {"id": rec_id}
            )
            clip_paths = [row[0] for row in rows.fetchall()]

            assert clip_path_fail in clip_paths
            assert None in clip_paths
            assert clip_path_success not in clip_paths

            row_rec = await session.execute(
                text("SELECT deleted_at IS NOT NULL FROM recordings WHERE id = :id"), {"id": rec_id}
            )
            assert row_rec.scalar() is True

        await engine.dispose()
