"""Integration tests for the Upload Worker pipeline against real PostgreSQL.

This module tests the Database State-Machine boundary:
DB (Pending) -> poller -> UploadWorker -> audit_logger -> DB (Uploaded).
We mock the network/I-O boundaries (ffmpeg, rclone) to isolate the database
transitions and ensure the pipeline correctly logs to the uploads table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from silvasonic.core.config_schemas import CloudSyncSettings
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.models.system import Device
from silvasonic.processor.modules.rclone_client import RcloneResult
from silvasonic.processor.upload_worker import UploadWorker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


# Use testcontainers utility function if available (or duplicate engine creation)
def _build_url(container: PostgresContainer) -> str:
    port = container.get_exposed_port(5432)
    host = container.get_container_host_ip()
    return f"postgresql+asyncpg://silvasonic:silvasonic@{host}:{port}/silvasonic_test"


@pytest.fixture
def db_engine(postgres_container: PostgresContainer) -> Any:
    """Provide an async SQLAlchemy engine connected to the shared testcontainer."""
    engine = create_async_engine(_build_url(postgres_container))
    yield engine
    engine.sync_engine.dispose()


@pytest.fixture
def session_factory(db_engine: Any) -> Any:
    """Provide a sessionmaker for dependency injection."""
    return async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )


@pytest.fixture
def dummy_recordings_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory simulating the Recorder workspace."""
    workspace = tmp_path / "recorder_workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def upload_settings() -> CloudSyncSettings:
    """Provide valid sync settings so the worker doesn't abort early."""
    return CloudSyncSettings(
        enabled=True,
        remote_type="s3",
        remote_config={
            "access_key_id": "test",
            "secret_access_key": "test",
            "region": "us-east-1",
            "endpoint": "http://localhost:9000",
        },
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_pipeline_mock_rclone(
    session_factory: Any,
    dummy_recordings_dir: Path,
    upload_settings: CloudSyncSettings,
) -> None:
    """Seed recording -> poll -> mock encode -> mock rclone -> audit -> uploaded=true."""
    # 1. Create dummy local file
    test_device = "mic-alpha"
    rel_path = Path(test_device) / "data" / "raw" / "test1.wav"
    abs_path = dummy_recordings_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(b"dummy audio")

    # 2. Seed a pending recording
    async with session_factory() as session:
        session.add(MicrophoneProfile(slug="test-profile", name="Test Profile"))
        session.add(
            Device(
                name=test_device,
                serial_number=f"sn-{test_device}",
                model="dummy",
                profile_slug="test-profile",
            )
        )
        await session.flush()
        rec = Recording(
            time=datetime.now(UTC),
            sensor_id=test_device,
            duration=15,
            sample_rate=48000,
            filesize_raw=5000,
            file_raw=str(rel_path),
            file_processed=str(rel_path).replace("raw", "processed"),
            uploaded=False,
            local_deleted=False,
        )
        session.add(rec)
        await session.commit()
        rec_id = rec.id

    worker = UploadWorker(session_factory, AsyncMock(), dummy_recordings_dir)

    # 3. Patch I/O boundaries and Run Pipeline
    with (
        patch(
            "silvasonic.processor.upload_worker.encode_wav_to_flac", new_callable=AsyncMock
        ) as mock_encode,
        patch(
            "silvasonic.processor.modules.rclone_client.RcloneClient.upload_file",
            new_callable=AsyncMock,
        ) as mock_upload,
    ):
        mock_encode.return_value = abs_path.with_suffix(".flac")
        mock_upload.return_value = RcloneResult(True, 1024, "", 1.5, False)

        # Process a single batch
        success = await worker._process_batch("station-alpha", upload_settings, b"dummy-key")

    assert success is True
    mock_encode.assert_awaited_once()
    mock_upload.assert_awaited_once()

    # 4. Verify Database State Changes
    async with session_factory() as session:
        # Check that Recording.uploaded is now True
        updated_rec = await session.get(Recording, rec_id)
        assert updated_rec is not None
        assert updated_rec.uploaded is True

        # Check that audit log was created
        result = await session.execute(
            text("SELECT count(*) FROM uploads WHERE recording_id = :id"), {"id": rec_id}
        )
        count = result.scalar_one()
        assert count == 1, "Expected exactly 1 upload audit record for this recording"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_skips_already_uploaded(
    session_factory: Any,
    dummy_recordings_dir: Path,
    upload_settings: CloudSyncSettings,
) -> None:
    """uploaded=true recordings are excluded by work_poller."""
    test_device = "mic-beta"
    rel_path = Path(test_device) / "data" / "raw" / "test2.wav"
    abs_path = dummy_recordings_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(b"dummy audio")

    # Seed an ALREADY UPLOADED recording
    async with session_factory() as session:
        session.add(MicrophoneProfile(slug="test-profile", name="Test Profile"))
        session.add(
            Device(
                name=test_device,
                serial_number=f"sn-{test_device}",
                model="dummy",
                profile_slug="test-profile",
            )
        )
        await session.flush()
        rec = Recording(
            time=datetime.now(UTC),
            sensor_id=test_device,
            duration=15,
            sample_rate=48000,
            filesize_raw=5000,
            file_raw=str(rel_path),
            file_processed=str(rel_path).replace("raw", "processed"),
            uploaded=True,
            local_deleted=False,
        )
        session.add(rec)
        await session.commit()

    worker = UploadWorker(session_factory, AsyncMock(), dummy_recordings_dir)

    with (
        patch(
            "silvasonic.processor.upload_worker.encode_wav_to_flac", new_callable=AsyncMock
        ) as mock_encode,
        patch(
            "silvasonic.processor.modules.rclone_client.RcloneClient.upload_file",
            new_callable=AsyncMock,
        ) as mock_upload,
    ):
        await worker._process_batch("station-alpha", upload_settings, b"dummy-key")

    # I/O wrappers must not be called, since work_poller skips uploaded=True
    mock_encode.assert_not_called()
    mock_upload.assert_not_called()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_handles_missing_file(
    session_factory: Any,
    dummy_recordings_dir: Path,
    upload_settings: CloudSyncSettings,
) -> None:
    """Recording exists in DB but WAV file missing from disk -> logged appropriately."""
    # Missing file path
    test_device = "mic-gamma"
    rel_path = Path(test_device) / "data" / "raw" / "ghost-file.wav"
    # DO NOT create the file on disk

    async with session_factory() as session:
        session.add(MicrophoneProfile(slug="test-profile", name="Test Profile"))
        session.add(
            Device(
                name=test_device,
                serial_number=f"sn-{test_device}",
                model="dummy",
                profile_slug="test-profile",
            )
        )
        await session.flush()
        rec = Recording(
            time=datetime.now(UTC),
            sensor_id=test_device,
            duration=15,
            sample_rate=48000,
            filesize_raw=5000,
            file_raw=str(rel_path),
            file_processed=str(rel_path).replace("raw", "processed"),
            uploaded=False,
            local_deleted=False,
        )
        session.add(rec)
        await session.commit()

    worker = UploadWorker(session_factory, AsyncMock(), dummy_recordings_dir)

    with (
        patch(
            "silvasonic.processor.upload_worker.encode_wav_to_flac", new_callable=AsyncMock
        ) as mock_encode,
        patch(
            "silvasonic.processor.modules.rclone_client.RcloneClient.upload_file",
            new_callable=AsyncMock,
        ) as mock_upload,
    ):
        success = await worker._process_batch("station-alpha", upload_settings, b"dummy-key")

    # The batch should succeed, but the individual missing file should be skipped.
    assert success is True
    # encode and upload should not be called since checking file existence happens first
    mock_encode.assert_not_called()
    mock_upload.assert_not_called()
