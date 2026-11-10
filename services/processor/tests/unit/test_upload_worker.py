"""Unit tests for the main UploadWorker."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.database.models.system import Module, SettingsSection
from silvasonic.core.schemas.settings import SyncSettings, TimeWindow
from silvasonic.processor.modules.rclone_client import RcloneResult
from silvasonic.processor.modules.work_poller import PendingUpload
from silvasonic.processor.upload_worker import UploadWorker, _is_within_window


@pytest.mark.unit
def test_within_window() -> None:
    """A window crossing midnight (22:00-06:00) is evaluated in UTC."""
    window = TimeWindow(start="22:00", end="06:00")
    with patch("silvasonic.processor.upload_worker.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2024, 1, 1, 23, tzinfo=UTC)
        assert _is_within_window(window) is True

        mock_dt.now.return_value = datetime(2024, 1, 1, 12, tzinfo=UTC)
        assert _is_within_window(window) is False

        mock_dt.now.return_value = datetime(2024, 1, 1, 3, tzinfo=UTC)
        assert _is_within_window(window) is True


@pytest.mark.unit
def test_window_has_minute_resolution() -> None:
    """Window bounds are HH:MM; start is inclusive, end exclusive."""
    window = TimeWindow(start="08:30", end="17:45")
    with patch("silvasonic.processor.upload_worker.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2024, 1, 1, 8, 29, tzinfo=UTC)
        assert _is_within_window(window) is False
        mock_dt.now.return_value = datetime(2024, 1, 1, 8, 30, tzinfo=UTC)
        assert _is_within_window(window) is True
        mock_dt.now.return_value = datetime(2024, 1, 1, 17, 44, tzinfo=UTC)
        assert _is_within_window(window) is True
        mock_dt.now.return_value = datetime(2024, 1, 1, 17, 45, tzinfo=UTC)
        assert _is_within_window(window) is False


@pytest.mark.unit
def test_null_window_always_active() -> None:
    """No window means always active."""
    assert _is_within_window(None) is True


@pytest.fixture
def worker(tmp_path: Path) -> UploadWorker:
    session = AsyncMock()
    session.add = MagicMock()

    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = session

    health = MagicMock()
    recordings_dir = tmp_path / "recorder"
    worker = UploadWorker(session_factory, health, recordings_dir)
    return worker


@pytest.fixture(autouse=True)
def mock_encryption_key() -> Any:
    target = "silvasonic.processor.upload_worker.load_encryption_key"
    with patch(target, return_value=b"dummykey") as mock_key:
        yield mock_key


@pytest.mark.unit
@patch("silvasonic.processor.upload_worker.find_pending_uploads")
@patch("silvasonic.processor.upload_worker.encode_wav_to_flac")
@patch("silvasonic.processor.upload_worker.RcloneClient")
@patch("silvasonic.processor.upload_worker.log_upload_attempt")
async def test_poll_loop_processes_pending(
    mock_log: MagicMock,
    mock_rclone_cls: MagicMock,
    mock_encode: MagicMock,
    mock_find: MagicMock,
    worker: UploadWorker,
    tmp_path: Path,
) -> None:
    """Test the happy path of finding, encoding, and uploading a file."""
    dummy_wav = tmp_path / "test.wav"
    dummy_wav.write_bytes(b"data")

    pending = PendingUpload(
        recording_id=uuid.UUID(int=1),
        raw_path=dummy_wav,
        hardware_id="mic1",
        station_name="",
        started_at=datetime.now(UTC),
        profile_slug="prof1",
    )
    mock_find.return_value = [pending]

    dummy_flac = tmp_path / "test.flac"
    dummy_flac.write_bytes(b"flac data")
    mock_encode.return_value = dummy_flac

    mock_rclone = AsyncMock()
    mock_rclone.upload_file.return_value = RcloneResult(
        success=True,
        bytes_transferred=9,
        error_message=None,
        duration_s=1.0,
        is_connection_error=False,
    )
    mock_rclone_cls.return_value = mock_rclone

    conf = {
        "access_key_id": "d",
        "secret_access_key": "d",
        "region": "d",
        "endpoint": "d",
        "acl": "private",
    }
    settings = SyncSettings(remote_type="s3", remote_config=conf)

    success = await worker._process_batch("my-station", settings, b"dummy-key")

    assert success is True
    mock_encode.assert_called_once()
    mock_rclone.upload_file.assert_called_once()
    mock_log.assert_called_once()
    assert not dummy_flac.exists()


@pytest.mark.unit
@patch("silvasonic.processor.upload_worker.find_pending_uploads")
@patch("silvasonic.processor.upload_worker.encode_wav_to_flac")
@patch("silvasonic.processor.upload_worker.RcloneClient")
@patch("silvasonic.processor.upload_worker.log_upload_attempt")
async def test_connection_error_aborts_batch(
    mock_log: MagicMock,
    mock_rclone_cls: MagicMock,
    mock_encode: MagicMock,
    mock_find: MagicMock,
    worker: UploadWorker,
    tmp_path: Path,
) -> None:
    """Test that a connection error prevents subsequent uploads in the batch."""
    dummy_wav = tmp_path / "test.wav"
    dummy_wav.touch()

    p1 = PendingUpload(uuid.UUID(int=1), dummy_wav, "mic1", "", datetime.now(UTC), "prof1")
    p2 = PendingUpload(uuid.UUID(int=2), dummy_wav, "mic1", "", datetime.now(UTC), "prof1")
    mock_find.return_value = [p1, p2]

    dummy_flac = tmp_path / "test.flac"
    dummy_flac.touch()
    mock_encode.return_value = dummy_flac

    mock_rclone = AsyncMock()
    mock_rclone.upload_file.return_value = RcloneResult(
        success=False,
        bytes_transferred=0,
        error_message="timeout",
        duration_s=1.0,
        is_connection_error=True,
    )
    mock_rclone_cls.return_value = mock_rclone

    conf = {
        "access_key_id": "d",
        "secret_access_key": "d",
        "region": "d",
        "endpoint": "d",
        "acl": "private",
    }
    settings = SyncSettings(remote_type="s3", remote_config=conf)
    success = await worker._process_batch("my-station", settings, b"dummy-key")

    assert success is False
    assert mock_encode.call_count == 1
    assert mock_rclone.upload_file.call_count == 1


@pytest.mark.unit
@patch("silvasonic.processor.upload_worker.find_pending_uploads")
@patch("silvasonic.processor.upload_worker.encode_wav_to_flac")
@patch("silvasonic.processor.upload_worker.RcloneClient")
async def test_missing_file_skipped(
    mock_rclone_cls: MagicMock,
    mock_encode: MagicMock,
    mock_find: MagicMock,
    worker: UploadWorker,
    tmp_path: Path,
) -> None:
    """Test that missing WAV files are skipped gracefully."""
    missing_wav = tmp_path / "missing.wav"
    p1 = PendingUpload(uuid.UUID(int=1), missing_wav, "mic1", "", datetime.now(UTC), "prof1")
    mock_find.return_value = [p1]

    conf = {
        "access_key_id": "d",
        "secret_access_key": "d",
        "region": "d",
        "endpoint": "d",
        "acl": "private",
    }
    settings = SyncSettings(remote_type="s3", remote_config=conf)
    success = await worker._process_batch("my-station", settings, b"dummy-key")

    assert success is True
    mock_encode.assert_not_called()


# ────────────────────────────────────────────────────
# Regression: UploadWorker passes recordings_dir
# ────────────────────────────────────────────────────


@pytest.mark.unit
@patch("silvasonic.processor.upload_worker.find_pending_uploads")
async def test_process_batch_passes_recordings_dir(
    mock_find: MagicMock,
    worker: UploadWorker,
) -> None:
    """UploadWorker._process_batch passes recordings_dir to find_pending_uploads.

    Regression: UploadWorker never provided recordings_dir to the poller,
    resulting in relative paths and permanent file_missing warnings.
    """
    mock_find.return_value = []

    conf = {
        "access_key_id": "d",
        "secret_access_key": "d",
        "region": "d",
        "endpoint": "d",
        "acl": "private",
    }
    settings = SyncSettings(remote_type="s3", remote_config=conf)
    await worker._process_batch("my-station", settings, b"dummy-key")

    mock_find.assert_called_once()
    call_args = mock_find.call_args
    # recordings_dir must be the second positional arg (after session)
    assert call_args[1].get("recordings_dir") == worker._recordings_dir or (
        len(call_args[0]) >= 2 and call_args[0][1] == worker._recordings_dir
    )


# ────────────────────────────────────────────────────
# Regression: Encoding errors handled per-item
# ────────────────────────────────────────────────────


@pytest.mark.unit
@patch("silvasonic.processor.upload_worker.find_pending_uploads")
@patch("silvasonic.processor.upload_worker.encode_wav_to_flac")
@patch("silvasonic.processor.upload_worker.log_upload_attempt")
async def test_process_batch_handles_encoding_oserror_gracefully(
    mock_log: MagicMock,
    mock_encode: MagicMock,
    mock_find: MagicMock,
    worker: UploadWorker,
    tmp_path: Path,
) -> None:
    """_process_batch handles OSError from FLAC encoding without crashing.

    Regression: FileNotFoundError (ffmpeg missing) propagated past
    ``except FlacEncodingError`` and crashed the entire worker with a
    60-second retry loop. OSError must be caught per-item so the batch
    continues with the next file.
    """
    dummy_wav = tmp_path / "test.wav"
    dummy_wav.write_bytes(b"data")

    pending = PendingUpload(
        recording_id=uuid.UUID(int=1),
        raw_path=dummy_wav,
        hardware_id="mic1",
        station_name="",
        started_at=datetime.now(UTC),
        profile_slug="prof1",
    )
    mock_find.return_value = [pending]

    # Simulate ffmpeg binary not found
    mock_encode.side_effect = FileNotFoundError(2, "No such file or directory", "ffmpeg")

    conf = {
        "access_key_id": "d",
        "secret_access_key": "d",
        "region": "d",
        "endpoint": "d",
        "acl": "private",
    }
    settings = SyncSettings(remote_type="s3", remote_config=conf)

    # Must NOT raise — should handle gracefully and return True
    success = await worker._process_batch("my-station", settings, b"dummy-key")

    assert success is True
    mock_log.assert_called_once()  # Audit log should capture the failure


# ────────────────────────────────────────────────────
# _fetch_config()
# ────────────────────────────────────────────────────


@pytest.mark.unit
async def test_fetch_config_defaults_when_no_db_entry(
    worker: UploadWorker,
) -> None:
    """_fetch_config returns default station name when DB has no entry."""
    session = cast("MagicMock", worker.session_factory)().__aenter__.return_value
    session.get = AsyncMock(return_value=None)

    station, settings, enabled = await worker._fetch_config()

    assert station == "silvasonic"
    assert settings is None
    assert enabled is False  # no cloud_sync module row → switched off


@pytest.mark.unit
async def test_fetch_config_extracts_station_name(
    worker: UploadWorker,
) -> None:
    """_fetch_config reads the station name, sync settings and the module switch."""
    station_conf = MagicMock()
    station_conf.value = {"name": "waldstation-01"}

    module = MagicMock(spec=Module)
    module.enabled = True

    sync_conf = MagicMock()
    sync_conf.value = {
        "remote_type": "s3",
        "remote_config": {
            "access_key_id": "k",
            "secret_access_key": "s",
            "region": "eu",
            "endpoint": "http://s3",
            "acl": "private",
        },
    }

    session = cast("MagicMock", worker.session_factory)().__aenter__.return_value

    async def fake_get(model: Any, key: str) -> Any:
        if model is SettingsSection and key == "station":
            return station_conf
        if model is SettingsSection and key == "sync":
            return sync_conf
        if model is Module and key == "cloud_sync":
            return module
        return None

    session.get = AsyncMock(side_effect=fake_get)

    station, settings, enabled = await worker._fetch_config()

    assert station == "waldstation-01"
    assert settings is not None
    assert settings.remote_type == "s3"
    assert enabled is True


@pytest.mark.unit
async def test_fetch_config_returns_none_for_invalid_cloud_sync(
    worker: UploadWorker,
) -> None:
    """_fetch_config returns None settings when the sync JSONB causes error."""
    sync_conf = MagicMock()
    # poll_interval_s must be int → dict triggers ValidationError
    sync_conf.value = {"poll_interval_s": {"nested": "invalid"}}

    session = cast("MagicMock", worker.session_factory)().__aenter__.return_value

    async def fake_get(model: Any, key: str) -> Any:
        if model is SettingsSection and key == "sync":
            return sync_conf
        return None

    session.get = AsyncMock(side_effect=fake_get)

    station, settings, _enabled = await worker._fetch_config()

    assert station == "silvasonic"
    assert settings is None


# ────────────────────────────────────────────────────
# run() fatal error path + stop()
# ────────────────────────────────────────────────────


@pytest.mark.unit
async def test_run_exits_on_missing_encryption_key(
    tmp_path: Path,
) -> None:
    """run() exits immediately and reports fatal health on missing key."""
    session_factory = MagicMock()
    health = MagicMock()

    w = UploadWorker(session_factory, health, tmp_path)

    with patch(
        "silvasonic.processor.upload_worker.load_encryption_key",
        side_effect=RuntimeError("no key"),
    ):
        await w.run()

    health.update_status.assert_called_once()
    call_args = health.update_status.call_args
    assert call_args[0][1] is False  # healthy=False
    assert "fatal" in call_args[0][2].lower()


# ────────────────────────────────────────────────────
# The cloud_sync module switch gates the upload loop
# ────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(("enabled", "expected_batches"), [(False, 0), (True, 1)])
async def test_module_switch_gates_uploads(
    worker: UploadWorker, enabled: bool, expected_batches: int
) -> None:
    """Disabled cloud_sync module → no batch; enabled → the batch runs."""
    settings = SyncSettings(remote_type="s3")
    batches: list[str] = []

    async def fake_batch(station: str, _settings: SyncSettings, _key: bytes) -> bool:
        batches.append(station)
        return True

    async def stop_after_sleep(_seconds: int) -> None:
        worker._shutdown_event.set()

    with (
        patch.object(
            worker,
            "_fetch_config",
            new_callable=AsyncMock,
            return_value=("station", settings, enabled),
        ),
        patch.object(worker, "_process_batch", side_effect=fake_batch),
        patch.object(worker, "_sleep", side_effect=stop_after_sleep),
    ):
        await worker.run()

    assert len(batches) == expected_batches
    if not enabled:
        health = cast("MagicMock", worker.health)
        health.update_status.assert_any_call("upload_worker", True, "state: disabled")


@pytest.mark.unit
async def test_stop_sets_shutdown_event(worker: UploadWorker) -> None:
    """stop() sets the shutdown event so run() can exit."""
    assert not worker._shutdown_event.is_set()
    await worker.stop()
    assert worker._shutdown_event.is_set()
