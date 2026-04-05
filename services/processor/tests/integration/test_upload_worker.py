"""Integration tests for the Upload Worker.

Tests the full local encoding and auditing pipeline against a real PostgreSQL DB
while safely mocking only the final `.upload_file()` network call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from silvasonic.core.config_schemas import CloudSyncSettings
from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.session import _get_engine, _get_session_factory
from silvasonic.core.health import HealthMonitor
from silvasonic.processor.modules.rclone_client import RcloneResult
from silvasonic.processor.upload_worker import UploadWorker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

TEST_KEY = b"Kaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="


def _build_async_url(container: PostgresContainer) -> str:
    """Build an asyncpg connection URL from a testcontainer."""
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    return f"postgresql+asyncpg://silvasonic:silvasonic@{host}:{port}/silvasonic_test"


async def _seed_device_and_recording(session: AsyncSession, wav_path: Path) -> int:
    """Seed DB with necessary records and return the recording ID."""
    # Seed Device
    await session.execute(
        text("""
            INSERT INTO microphone_profiles (slug, name, is_system, config)
            VALUES ('default', 'Default Profile', true, '{}')
            ON CONFLICT (slug) DO NOTHING
        """)
    )

    await session.execute(
        text("""
            INSERT INTO devices (name, serial_number, model, config, workspace_name, profile_slug)
            VALUES ('mic-01', 'SN-01', 'TestMic', '{}', 'mic-01', 'default')
            ON CONFLICT (name) DO NOTHING
        """)
    )

    import json

    sync_config = json.dumps(
        {
            "enabled": True,
            "remote_type": "rclone",
            "remote_name": "gdrive",
            "schedule_start_hour": None,
            "schedule_end_hour": None,
        }
    )

    await session.execute(
        text("""
            INSERT INTO system_config (key, value)
            VALUES ('cloud_sync', :config)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """),
        {"config": sync_config},
    )

    rec = Recording(
        time=datetime.now(UTC),
        sensor_id="mic-01",
        file_raw=str(wav_path),
        duration=10.0,
        sample_rate=48000,
        filesize_raw=1000,
        uploaded=False,
    )
    session.add(rec)
    await session.commit()
    return rec.id


def _create_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import wave

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(b"\x00\x00" * 48000 * 2)  # 2 seconds


@pytest.mark.integration
class TestUploadWorkerIntegration:
    """Verify UploadWorker logic with local constraints."""

    @pytest.fixture(autouse=True)
    def setup_env(
        self, monkeypatch: pytest.MonkeyPatch, postgres_container: PostgresContainer
    ) -> None:
        """Inject testcontainer DB credentials into environment."""
        _get_engine.cache_clear()
        _get_session_factory.cache_clear()
        monkeypatch.setenv("POSTGRES_HOST", postgres_container.get_container_host_ip())
        monkeypatch.setenv("POSTGRES_PORT", str(postgres_container.get_exposed_port(5432)))
        monkeypatch.setenv("POSTGRES_USER", "silvasonic")
        monkeypatch.setenv("POSTGRES_PASSWORD", "silvasonic")
        monkeypatch.setenv("POSTGRES_DB", "silvasonic_test")
        monkeypatch.setenv("SILVASONIC_CRYPTO_KEY", TEST_KEY.decode("utf-8"))

    async def test_process_batch_success(
        self, postgres_container: PostgresContainer, tmp_path: Path, mocker: Any
    ) -> None:
        """Verify processing batch successfully encodes and audits without loop hanging."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        wav_path = tmp_path / "mic-01" / "data" / "processed" / "test.wav"
        _create_wav(wav_path)

        async with factory() as session:
            rec_id = await _seed_device_and_recording(session, wav_path)

        # Only the remote upload is faked
        mock_upload = mocker.patch(
            "silvasonic.processor.modules.rclone_client.RcloneClient.upload_file"
        )
        mock_upload.return_value = RcloneResult(
            success=True,
            bytes_transferred=1024,
            duration_s=1.0,
            is_connection_error=False,
            error_message="",
        )

        health = HealthMonitor()
        worker = UploadWorker(factory, health, tmp_path)

        result = await worker._process_batch(
            station_name="silvasonic",
            settings=CloudSyncSettings(enabled=True, remote_type="rclone", remote_name="remote"),
            encryption_key=TEST_KEY,
        )

        assert result is True
        mock_upload.assert_called_once()

        # Temporary FLAC file should be cleaned up locally
        flac_path = wav_path.with_suffix(".flac")
        assert not flac_path.exists()

        # Verify Database Updates
        async with factory() as session:
            rec = await session.get(Recording, rec_id)
            assert rec is not None
            assert rec.uploaded is True

            rows = await session.execute(
                text("SELECT success, size, error_message FROM uploads WHERE recording_id = :rid"),
                {"rid": rec_id},
            )
            upload_logs = rows.fetchall()
            assert len(upload_logs) == 1
            assert upload_logs[0][0] is True  # success
            assert upload_logs[0][1] == 1024  # transferred bytes

        await engine.dispose()
