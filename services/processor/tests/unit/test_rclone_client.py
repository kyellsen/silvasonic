"""Unit tests for the RcloneClient."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from silvasonic.core.crypto import generate_key
from silvasonic.core.schemas.system_config import CloudSyncSettings
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


# ────────────────────────────────────────────────────
# Crypto contract: _decrypt_config()
# ────────────────────────────────────────────────────


@pytest.mark.unit
class TestDecryptConfig:
    """Tests for RcloneClient._decrypt_config() — the crypto boundary.

    Data-integrity contract: enc: values must be decrypted exactly once,
    plain values must pass through unmodified. If this breaks, either
    cleartext credentials leak into rclone.conf, or encrypted values
    get double-decrypted (garbled).
    """

    def test_plain_values_pass_through(
        self,
        settings: CloudSyncSettings,
        encryption_key: bytes,
    ) -> None:
        """Config with only plain values passes through unchanged."""
        client = RcloneClient(settings, encryption_key)

        result = client._decrypt_config(
            {
                "endpoint": "https://s3.example.com",
                "region": "eu-central-1",
            }
        )

        assert result == {
            "endpoint": "https://s3.example.com",
            "region": "eu-central-1",
        }

    def test_encrypted_values_are_decrypted(
        self,
        settings: CloudSyncSettings,
        encryption_key: bytes,
    ) -> None:
        """Config with enc:-prefixed values are decrypted to plaintext."""
        from silvasonic.core.crypto import encrypt_value

        secret = "my-s3-secret-key"
        encrypted = encrypt_value(secret, encryption_key)

        client = RcloneClient(settings, encryption_key)

        result = client._decrypt_config(
            {
                "access_key_id": "AKIA1234",
                "secret_access_key": encrypted,
            }
        )

        assert result["access_key_id"] == "AKIA1234"
        assert result["secret_access_key"] == secret

    def test_mixed_plain_and_encrypted(
        self,
        settings: CloudSyncSettings,
        encryption_key: bytes,
    ) -> None:
        """Mixed config: enc: values decrypted, plain values untouched."""
        from silvasonic.core.crypto import encrypt_value

        password = "WebDAV-P@ss!"
        encrypted_pass = encrypt_value(password, encryption_key)

        client = RcloneClient(settings, encryption_key)

        result = client._decrypt_config(
            {
                "url": "https://dav.example.com/remote.php/webdav/",
                "user": "admin",
                "pass": encrypted_pass,
                "vendor": "nextcloud",
            }
        )

        assert result["url"] == "https://dav.example.com/remote.php/webdav/"
        assert result["user"] == "admin"
        assert result["pass"] == password
        assert result["vendor"] == "nextcloud"

    def test_non_string_values_pass_through(
        self,
        settings: CloudSyncSettings,
        encryption_key: bytes,
    ) -> None:
        """Non-string values (int, bool) pass through without error."""
        client = RcloneClient(settings, encryption_key)

        result = client._decrypt_config(
            {
                "chunk_size": 5242880,
                "disable_http2": True,
                "endpoint": "https://s3.example.com",
            }
        )

        assert result["chunk_size"] == 5242880
        assert result["disable_http2"] is True
        assert result["endpoint"] == "https://s3.example.com"
