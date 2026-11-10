"""Integration tests for the Upload Worker.

Tests the full local encoding and auditing pipeline against a real PostgreSQL DB
while safely mocking only the final `.upload_file()` network call.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.models.system import Microphone
from silvasonic.core.database.session import (
    _get_engine,
    _get_session_factory,
    create_station_engine,
)
from silvasonic.core.health import HealthMonitor
from silvasonic.core.schemas.settings import SyncSettings
from silvasonic.processor.modules.rclone_client import RcloneResult
from silvasonic.processor.upload_worker import UploadWorker
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_KEY = b"Kaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="


async def _set_cloud_sync_module(session: AsyncSession, enabled: bool) -> None:
    """Upsert the ``cloud_sync`` row of the ``modules`` table."""
    await session.execute(
        text("""
            INSERT INTO modules (id, enabled) VALUES ('cloud_sync', :enabled)
            ON CONFLICT (id) DO UPDATE SET enabled = EXCLUDED.enabled
        """),
        {"enabled": enabled},
    )


async def _seed_microphone_and_recording(session: AsyncSession, wav_path: Path) -> uuid.UUID:
    """Seed DB with necessary records and return the recording ID."""
    # Seed Microphone
    await session.execute(
        text("""
            INSERT INTO microphone_profiles (slug, name, built_in, config)
            VALUES ('default', 'Default Profile', true, '{}')
            ON CONFLICT (slug) DO NOTHING
        """)
    )

    await session.execute(
        text("""
            INSERT INTO microphones (hardware_id, name, serial_number, model, hardware,
                                     workspace_name, profile_slug)
            VALUES ('mic-01', 'TestMic', 'SN-01', 'TestMic', '{}', 'mic-01', 'default')
            ON CONFLICT (hardware_id) DO NOTHING
        """)
    )

    sync_config = json.dumps(
        {
            "remote_type": "rclone",
            "remote_name": "gdrive",
            "window": None,
        }
    )

    await session.execute(
        text("""
            INSERT INTO settings (section, value)
            VALUES ('sync', :config)
            ON CONFLICT (section) DO UPDATE SET value = EXCLUDED.value
        """),
        {"config": sync_config},
    )
    await _set_cloud_sync_module(session, True)

    microphone_id = (
        await session.execute(select(Microphone.id).where(Microphone.hardware_id == "mic-01"))
    ).scalar_one()

    rec = Recording(
        started_at=datetime.now(UTC),
        microphone_id=microphone_id,
        raw_path=str(wav_path),
        duration_s=10.0,
        sample_rate_hz=48000,
        raw_size_bytes=1000,
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
    def setup_env(self, monkeypatch: pytest.MonkeyPatch, station_db: Path) -> None:
        """Inject testcontainer DB credentials into environment."""
        _get_engine.cache_clear()
        _get_session_factory.cache_clear()
        monkeypatch.setenv("SILVASONIC_DB_PATH", str(station_db))
        monkeypatch.setenv("SILVASONIC_CRYPTO_KEY", TEST_KEY.decode("utf-8"))

    async def test_process_batch_success(
        self, station_db: Path, tmp_path: Path, mocker: Any
    ) -> None:
        """Verify processing batch successfully encodes and audits without loop hanging."""
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        wav_path = tmp_path / "mic-01" / "data" / "processed" / "test.wav"
        _create_wav(wav_path)

        async with factory() as session:
            rec_id = await _seed_microphone_and_recording(session, wav_path)

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
            settings=SyncSettings(remote_type="rclone", remote_name="remote"),
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
            assert rec.uploaded_at is not None

            rows = await session.execute(
                text(
                    "SELECT success, size_bytes, error_message, id, attempted_at "
                    "FROM uploads WHERE recording_id = :rid"
                ),
                {"rid": rec_id},
            )
            upload_logs = rows.fetchall()
            assert len(upload_logs) == 1
            assert upload_logs[0][0] == 1  # success (raw SQL: booleans are 0/1)
            assert upload_logs[0][1] == 1024  # transferred bytes
            # raw SQL: the id comes back as the stored 32 hex digits (ADR-0037)
            assert uuid.UUID(upload_logs[0][3]).version == 7
            assert upload_logs[0][4] is not None

        await engine.dispose()

    @pytest.mark.parametrize("enabled", [False, True])
    async def test_fetch_config_reads_module_switch(
        self, station_db: Path, tmp_path: Path, enabled: bool
    ) -> None:
        """The upload switch is the cloud_sync row of the modules table."""
        engine = create_station_engine(station_db)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        wav_path = tmp_path / "mic-01" / "data" / "processed" / "test.wav"
        _create_wav(wav_path)
        async with factory() as session:
            await _seed_microphone_and_recording(session, wav_path)
            await _set_cloud_sync_module(session, enabled)
            await session.execute(
                text("""
                    INSERT INTO settings (section, value)
                    VALUES ('station', '{"name": "Waldstation"}')
                    ON CONFLICT (section) DO UPDATE SET value = EXCLUDED.value
                """)
            )
            await session.commit()

        worker = UploadWorker(factory, HealthMonitor(), tmp_path)
        station_name, settings, module_enabled = await worker._fetch_config()

        assert station_name == "Waldstation"
        assert settings is not None
        assert settings.remote_type == "rclone"
        assert module_enabled is enabled

        await engine.dispose()
