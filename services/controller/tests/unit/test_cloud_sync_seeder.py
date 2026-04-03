"""Unit tests for CloudSyncSeeder — env-driven cloud credential seeding.

Covers all-vars-set, partial vars, no vars, UPSERT overwrite,
missing encryption key, and WebDAV auto-vendor detection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from silvasonic.controller.seeder import CloudSyncSeeder


def _make_env(
    *,
    remote_type: str = "webdav",
    remote_url: str = "https://cloud.example.de/remote.php/webdav/",
    remote_user: str = "admin",
    remote_pass: str = "secret123",
    encryption_key: str | None = None,
) -> dict[str, str]:
    """Build a complete set of cloud sync env vars."""
    env: dict[str, str] = {
        "SILVASONIC_CLOUD_REMOTE_TYPE": remote_type,
        "SILVASONIC_CLOUD_REMOTE_URL": remote_url,
        "SILVASONIC_CLOUD_REMOTE_USER": remote_user,
        "SILVASONIC_CLOUD_REMOTE_PASS": remote_pass,
    }
    if encryption_key is not None:
        env["SILVASONIC_ENCRYPTION_KEY"] = encryption_key
    return env


@pytest.mark.unit
class TestCloudSyncSeeder:
    """Tests for the CloudSyncSeeder class."""

    async def test_all_env_vars_set_seeds_encrypted(self) -> None:
        """All 4 vars → system_config updated with enc: values, enabled=true."""
        key = Fernet.generate_key().decode()
        env = _make_env(encryption_key=key)

        session = AsyncMock(add=MagicMock())
        session.get = AsyncMock(return_value=None)  # No existing cloud_sync

        seeder = CloudSyncSeeder()
        with patch.dict("os.environ", env, clear=True):
            await seeder.seed(session)

        # Should have inserted
        assert session.add.call_count == 1
        added = session.add.call_args[0][0]
        assert added.key == "cloud_sync"

        value = added.value
        assert value["enabled"] is True
        assert value["remote_type"] == "webdav"
        assert value["remote_config"]["user"].startswith("enc:")
        assert value["remote_config"]["pass"].startswith("enc:")
        # URL should NOT be encrypted
        assert value["remote_config"]["url"] == "https://cloud.example.de/remote.php/webdav/"

    async def test_partial_env_vars_skips(self) -> None:
        """Only 2 of 4 vars → no DB change, debug log."""
        env = {
            "SILVASONIC_CLOUD_REMOTE_TYPE": "webdav",
            "SILVASONIC_CLOUD_REMOTE_URL": "https://example.com/webdav/",
            # Missing USER and PASS
        }

        session = AsyncMock(add=MagicMock())
        seeder = CloudSyncSeeder()
        with patch.dict("os.environ", env, clear=True):
            await seeder.seed(session)

        session.add.assert_not_called()
        session.get.assert_not_called()

    async def test_no_env_vars_skips(self) -> None:
        """No vars → no DB change, no error."""
        session = AsyncMock(add=MagicMock())
        seeder = CloudSyncSeeder()
        with patch.dict("os.environ", {}, clear=True):
            await seeder.seed(session)

        session.add.assert_not_called()
        session.get.assert_not_called()

    async def test_upsert_overwrites_existing(self) -> None:
        """Existing cloud_sync in DB → overwritten with new .env values."""
        key = Fernet.generate_key().decode()
        env = _make_env(
            remote_type="s3",
            remote_url="https://s3.amazonaws.com",
            remote_user="AKID",
            remote_pass="secret",
            encryption_key=key,
        )

        # Simulate existing cloud_sync in DB with different values
        existing = MagicMock()
        existing.value = {
            "enabled": False,
            "poll_interval": 60,
            "bandwidth_limit": "2M",
            "schedule_start_hour": 22,
            "schedule_end_hour": 6,
            "remote_type": "webdav",
            "remote_config": {"url": "old"},
        }

        session = AsyncMock(add=MagicMock())
        session.get = AsyncMock(return_value=existing)

        seeder = CloudSyncSeeder()
        with patch.dict("os.environ", env, clear=True):
            await seeder.seed(session)

        # Should NOT have called session.add (UPSERT = update existing)
        session.add.assert_not_called()

        # Existing value should be updated with merged values
        merged = existing.value
        assert merged["enabled"] is True
        assert merged["remote_type"] == "s3"
        assert merged["remote_config"]["user"].startswith("enc:")
        # Preserved from existing: poll_interval, bandwidth, schedule
        assert merged["poll_interval"] == 60
        assert merged["bandwidth_limit"] == "2M"
        assert merged["schedule_start_hour"] == 22

    async def test_missing_encryption_key_errors(self) -> None:
        """Credentials set but no SILVASONIC_ENCRYPTION_KEY → clear error, skip."""
        env = _make_env()  # No encryption_key

        session = AsyncMock(add=MagicMock())
        seeder = CloudSyncSeeder()
        with patch.dict("os.environ", env, clear=True):
            await seeder.seed(session)

        session.add.assert_not_called()
        session.get.assert_not_called()

    async def test_webdav_auto_vendor_nextcloud(self) -> None:
        """remote_type=webdav + URL with /webdav/ → vendor=nextcloud auto-set."""
        key = Fernet.generate_key().decode()
        env = _make_env(
            remote_url="https://my-storageshare.de/remote.php/webdav/",
            encryption_key=key,
        )

        session = AsyncMock(add=MagicMock())
        session.get = AsyncMock(return_value=None)

        seeder = CloudSyncSeeder()
        with patch.dict("os.environ", env, clear=True):
            await seeder.seed(session)

        added = session.add.call_args[0][0]
        assert added.value["remote_config"]["vendor"] == "nextcloud"
