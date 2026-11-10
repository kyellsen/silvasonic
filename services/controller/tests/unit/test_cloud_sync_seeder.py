"""Unit tests for CloudSyncSeeder — env-driven cloud credential seeding.

Covers all-vars-set, partial vars, no vars, UPSERT overwrite,
missing encryption key, WebDAV auto-vendor detection, and the
``cloud_sync`` module switch.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from silvasonic.controller.seeder import CloudSyncSeeder
from silvasonic.core.database.models.system import Module, SettingsSection


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


def _session_with(*, sync: Any = None, module: Module | None = None) -> tuple[AsyncMock, MagicMock]:
    """Mock session whose ``get()`` returns *sync* / *module* by model class."""

    async def _get(model: type, key: str) -> Any:
        if model is SettingsSection and key == "sync":
            return sync
        if model is Module and key == "cloud_sync":
            return module
        return None

    add = MagicMock()
    session = AsyncMock(add=add)
    session.get = AsyncMock(side_effect=_get)
    return session, add


def _added(add: MagicMock, model: type) -> list[Any]:
    """Objects of *model* passed to ``session.add()``."""
    return [c.args[0] for c in add.call_args_list if isinstance(c.args[0], model)]


@pytest.mark.unit
class TestCloudSyncSeeder:
    """Tests for the CloudSyncSeeder class."""

    async def test_all_env_vars_set_seeds_encrypted(self) -> None:
        """All 4 vars → sync section with enc: values, cloud_sync module on."""
        key = Fernet.generate_key().decode()
        env = _make_env(encryption_key=key)

        session, add = _session_with()  # No sync section, no module row

        seeder = CloudSyncSeeder()
        with patch.dict("os.environ", env, clear=True):
            await seeder.seed(session)

        # Should have inserted the sync section and the module switch
        sections = _added(add, SettingsSection)
        assert len(sections) == 1
        assert sections[0].section == "sync"
        modules = _added(add, Module)
        assert len(modules) == 1
        assert modules[0].id == "cloud_sync"
        assert modules[0].enabled is True

        value = sections[0].value
        assert "enabled" not in value  # the switch lives in modules
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
        """Existing sync section in DB → overwritten with new .env values."""
        key = Fernet.generate_key().decode()
        env = _make_env(
            remote_type="s3",
            remote_url="https://s3.amazonaws.com",
            remote_user="AKID",
            remote_pass="secret",
            encryption_key=key,
        )

        # Simulate existing sync section in DB with different values
        existing = MagicMock()
        existing.value = {
            "poll_interval_s": 60,
            "bandwidth_limit_bytes_per_s": 2_097_152,
            "window": {"start": "22:00", "end": "06:00"},
            "remote_type": "webdav",
            "remote_config": {"url": "old"},
        }
        module = Module(id="cloud_sync", enabled=False)

        session, add = _session_with(sync=existing, module=module)

        seeder = CloudSyncSeeder()
        with patch.dict("os.environ", env, clear=True):
            await seeder.seed(session)

        # Should NOT have called session.add (UPSERT = update existing rows)
        add.assert_not_called()

        # Existing value should be updated with merged values
        merged: dict[str, Any] = existing.value
        assert merged["remote_type"] == "s3"
        assert merged["remote_config"]["user"].startswith("enc:")
        # Preserved from existing: poll interval, bandwidth, window
        assert merged["poll_interval_s"] == 60
        assert merged["bandwidth_limit_bytes_per_s"] == 2_097_152
        assert merged["window"] == {"start": "22:00", "end": "06:00"}
        # The upload is switched on in the modules table
        assert module.enabled is True

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

        session, add = _session_with()

        seeder = CloudSyncSeeder()
        with patch.dict("os.environ", env, clear=True):
            await seeder.seed(session)

        added = _added(add, SettingsSection)[0]
        assert added.value["remote_config"]["vendor"] == "nextcloud"
