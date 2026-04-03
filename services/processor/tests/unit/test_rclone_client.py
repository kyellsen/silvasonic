"""Unit tests for the RcloneClient."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from silvasonic.core.config_schemas import CloudSyncSettings
from silvasonic.core.crypto import generate_key
from silvasonic.processor.modules.rclone_client import RcloneClient


@pytest.fixture
def encryption_key() -> bytes:
    return generate_key().encode("utf-8")


@pytest.fixture
def settings() -> CloudSyncSettings:
    return CloudSyncSettings(
        enabled=True,
        remote_type="s3",
        remote_config={
            "access_key_id": "test-key",
            "secret_access_key": "test-secret",
            "endpoint": "http://localhost:9000",
            "region": "us-east-1",
            "acl": "private",
        },
    )


@pytest.fixture
def dummy_flac(tmp_path: Path) -> Path:
    p = tmp_path / "test.flac"
    p.write_bytes(b"fake flac data")
    return p


# ────────────────────────────────────────────────────
# Regression: rclone stderr must appear in structured log
# ────────────────────────────────────────────────────


@pytest.mark.unit
async def test_rclone_failure_logs_stderr(
    settings: CloudSyncSettings,
    encryption_key: bytes,
    dummy_flac: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """rclone.upload.failed log entry must include the stderr error text.

    Regression: stderr was captured and stored in RcloneResult.error_message
    but was NOT included in the structured log output, making it impossible
    to diagnose rclone failures without querying the uploads audit table.
    """
    error_text = "AccessDenied: Access Denied"

    async def mock_exec(*args: Any, **kwargs: Any) -> AsyncMock:
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate.return_value = (b"", error_text.encode())
        return proc

    client = RcloneClient(settings, encryption_key)

    with (
        patch("asyncio.create_subprocess_exec", side_effect=mock_exec),
        patch.object(
            client, "_generate_rclone_conf", new_callable=AsyncMock, return_value=dummy_flac
        ),
    ):
        result = await client.upload_file(dummy_flac, "bucket/path/file.flac")

    assert result.success is False
    assert result.error_message is not None
    assert "AccessDenied" in result.error_message

    # The critical assertion: error text must be in the log call.
    # We verify via the RcloneResult since structlog capture requires
    # additional setup. The log.error call must include 'error' kwarg.
    # We'll check the source code behavior by inspecting the result.
    # A proper test would use structlog.testing.capture_logs() — see below.


@pytest.mark.unit
async def test_rclone_failure_log_includes_error_kwarg(
    settings: CloudSyncSettings,
    encryption_key: bytes,
    dummy_flac: Path,
) -> None:
    """Verify log.error is called with 'error' keyword containing stderr.

    Regression: Without error text in the log, operators cannot diagnose
    why rclone fails without direct DB queries.
    """
    error_text = "bucket not found: 404"

    async def mock_exec(*args: Any, **kwargs: Any) -> AsyncMock:
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate.return_value = (b"", error_text.encode())
        return proc

    client = RcloneClient(settings, encryption_key)

    with (
        patch("asyncio.create_subprocess_exec", side_effect=mock_exec),
        patch.object(
            client, "_generate_rclone_conf", new_callable=AsyncMock, return_value=dummy_flac
        ),
        patch("silvasonic.processor.modules.rclone_client.log") as mock_log,
    ):
        result = await client.upload_file(dummy_flac, "bucket/path/file.flac")

    assert result.success is False

    # Verify log.error was called with 'error' kwarg containing stderr
    mock_log.error.assert_called_once()
    call_kwargs = mock_log.error.call_args[1]
    assert "error" in call_kwargs, (
        f"log.error missing 'error' kwarg. Got: {sorted(call_kwargs.keys())}"
    )
    assert error_text in call_kwargs["error"]
