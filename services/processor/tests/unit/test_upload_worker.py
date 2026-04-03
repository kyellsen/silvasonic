"""Unit tests for the main UploadWorker."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.config_schemas import CloudSyncSettings
from silvasonic.processor.modules.rclone_client import RcloneResult
from silvasonic.processor.modules.work_poller import PendingUpload
from silvasonic.processor.upload_worker import UploadWorker, _is_within_window


@pytest.mark.unit
def test_within_window() -> None:
    """Test time window constraints."""
    with patch("silvasonic.processor.upload_worker.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2024, 1, 1, 23, tzinfo=UTC)
        assert _is_within_window(22, 6) is True

        mock_dt.now.return_value = datetime(2024, 1, 1, 12, tzinfo=UTC)
        assert _is_within_window(22, 6) is False

        mock_dt.now.return_value = datetime(2024, 1, 1, 3, tzinfo=UTC)
        assert _is_within_window(22, 6) is True


@pytest.mark.unit
def test_null_schedule_always_active() -> None:
    """Test null schedule means always active."""
    assert _is_within_window(None, None) is True
    assert _is_within_window(22, None) is True
    assert _is_within_window(None, 6) is True


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
async def test_upload_disabled_skips(worker: UploadWorker) -> None:
    """Test that the worker skips DB polling if disabled."""

    async def break_loop(*args: Any, **kwargs: Any) -> None:
        worker._shutdown_event.set()

    with patch.object(worker, "_sleep", side_effect=break_loop) as mock_sleep:
        worker._fetch_config = AsyncMock(return_value=("station", CloudSyncSettings(enabled=False)))  # type: ignore
        await worker.run()

        health_mock = worker.health.update_status
        health_mock.assert_called_with("upload_worker", True, "state: disabled")  # type: ignore
        mock_sleep.assert_called()


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
        recording_id=1,
        file_raw=dummy_wav,
        sensor_id="mic1",
        station_name="",
        time=datetime.now(UTC),
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
    settings = CloudSyncSettings(enabled=True, remote_type="s3", remote_config=conf)

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

    p1 = PendingUpload(1, dummy_wav, "mic1", "", datetime.now(UTC), "prof1")
    p2 = PendingUpload(2, dummy_wav, "mic1", "", datetime.now(UTC), "prof1")
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
    settings = CloudSyncSettings(enabled=True, remote_type="s3", remote_config=conf)
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
    p1 = PendingUpload(1, missing_wav, "mic1", "", datetime.now(UTC), "prof1")
    mock_find.return_value = [p1]

    conf = {
        "access_key_id": "d",
        "secret_access_key": "d",
        "region": "d",
        "endpoint": "d",
        "acl": "private",
    }
    settings = CloudSyncSettings(enabled=True, remote_type="s3", remote_config=conf)
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
    settings = CloudSyncSettings(enabled=True, remote_type="s3", remote_config=conf)
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
        recording_id=1,
        file_raw=dummy_wav,
        sensor_id="mic1",
        station_name="",
        time=datetime.now(UTC),
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
    settings = CloudSyncSettings(enabled=True, remote_type="s3", remote_config=conf)

    # Must NOT raise — should handle gracefully and return True
    success = await worker._process_batch("my-station", settings, b"dummy-key")

    assert success is True
    mock_log.assert_called_once()  # Audit log should capture the failure
