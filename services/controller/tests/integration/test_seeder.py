"""Integration tests: Seeders ↔ real TimescaleDB.

Verifies that ConfigSeeder, ProfileBootstrapper, and AuthSeeder
actually insert data into a real PostgreSQL/TimescaleDB instance.

Uses the shared ``postgres_container`` fixture from ``silvasonic-test-utils``
(surfaced via root ``conftest.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from silvasonic.controller.seeder import (
    AuthSeeder,
    ConfigSeeder,
    ManagedServiceSeeder,
    ProfileBootstrapper,
)
from silvasonic.test_utils.helpers import build_postgres_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


def _make_defaults_yml(tmp_path: Path) -> Path:
    """Create a valid defaults.yml for integration testing."""
    yml = tmp_path / "defaults.yml"
    yml.write_text(
        """
system:
  latitude: 53.55
  longitude: 9.99
  max_recorders: 5
  station_name: "Integration Test Station"
  auto_enrollment: true

auth:
  default_username: "admin"
  default_password: "testpass123"
""",
        encoding="utf-8",
    )
    return yml


def _make_profile_yml(tmp_path: Path) -> Path:
    """Create a valid profile YAML for integration testing."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    yml = profiles_dir / "integration_mic.yml"
    yml.write_text(
        """
schema_version: "1.0"
slug: integration_mic
name: Integration Test Microphone
description: A profile for integration testing.
audio:
  sample_rate: 48000
  channels: 1
  format: S16LE
processing:
  gain_db: 0.0
  chunk_size: 4096
stream:
  raw_enabled: true
  processed_enabled: true
  live_stream_enabled: false
  segment_duration_s: 15
""",
        encoding="utf-8",
    )
    return profiles_dir


@pytest.mark.integration
class TestConfigSeederIntegration:
    """Verify ConfigSeeder inserts actual rows into a real PostgreSQL DB."""

    async def test_seed_inserts_system_config(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """ConfigSeeder inserts 'system' key into system_config table."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        yml = _make_defaults_yml(tmp_path)
        seeder = ConfigSeeder(defaults_path=yml)

        async with session_factory() as session:
            await seeder.seed(session)
            await session.commit()

        # Verify the row exists in the real DB
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT value FROM system_config WHERE key = 'system'")
            )
            row = result.scalar_one_or_none()

        await engine.dispose()

        assert row is not None, "system_config row not found after seeding"
        assert row["station_name"] == "Integration Test Station"
        assert row["auto_enrollment"] is True

    async def test_seed_is_idempotent(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Running ConfigSeeder twice does not create duplicate rows."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        yml = _make_defaults_yml(tmp_path)
        seeder = ConfigSeeder(defaults_path=yml)

        # Seed twice
        async with session_factory() as session:
            await seeder.seed(session)
            await session.commit()

        async with session_factory() as session:
            await seeder.seed(session)
            await session.commit()

        # Verify only one row
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT count(*) FROM system_config WHERE key = 'system'")
            )
            count = result.scalar_one()

        await engine.dispose()

        assert count == 1, f"Expected 1 row, got {count}"


@pytest.mark.integration
class TestProfileBootstrapperIntegration:
    """Verify ProfileBootstrapper inserts actual profiles into a real PostgreSQL DB."""

    async def test_seed_inserts_profile(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """ProfileBootstrapper inserts a profile row into microphone_profiles table."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        profiles_dir = _make_profile_yml(tmp_path)
        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)

        async with session_factory() as session:
            await bootstrapper.seed(session)
            await session.commit()

        # Verify the profile exists
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT name, is_system FROM microphone_profiles WHERE slug = 'integration_mic'"
                )
            )
            row = result.one_or_none()

        await engine.dispose()

        assert row is not None, "microphone_profiles row not found after seeding"
        assert row[0] == "Integration Test Microphone"
        assert row[1] is True  # is_system


@pytest.mark.integration
class TestAuthSeederIntegration:
    """Verify AuthSeeder creates an admin user in a real PostgreSQL DB."""

    async def test_seed_creates_admin_with_bcrypt(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """AuthSeeder inserts an admin user with bcrypt-hashed password."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        yml = _make_defaults_yml(tmp_path)
        seeder = AuthSeeder(defaults_path=yml)

        async with session_factory() as session:
            await seeder.seed(session)
            await session.commit()

        # Verify the user exists and password is bcrypt-hashed
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT username, password_hash FROM users WHERE username = 'admin'")
            )
            row = result.one_or_none()

        await engine.dispose()

        assert row is not None, "admin user not found after seeding"
        assert row[0] == "admin"
        assert row[1].startswith("$2"), f"Expected bcrypt hash, got: {row[1][:10]}..."


@pytest.mark.integration
class TestRunAllSeedersIntegration:
    """Verify run_all_seeders executes all seeders against a real DB."""

    async def test_all_seeders_populate_db(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """run_all_seeders populates system_config, microphone_profiles, and users."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Create test YAML files
        yml = _make_defaults_yml(tmp_path)
        profiles_dir = _make_profile_yml(tmp_path)

        # Instantiate seeders with explicit test paths (no module-level
        # constants to patch — paths are resolved via cached functions).
        async with session_factory() as session:
            await ConfigSeeder(defaults_path=yml).seed(session)
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await AuthSeeder(defaults_path=yml).seed(session)
            await ManagedServiceSeeder().seed(session)
            await session.commit()

        # Verify all tables have data
        async with session_factory() as session:
            config_count = (
                await session.execute(text("SELECT count(*) FROM system_config"))
            ).scalar_one()
            profile_count = (
                await session.execute(text("SELECT count(*) FROM microphone_profiles"))
            ).scalar_one()
            user_count = (await session.execute(text("SELECT count(*) FROM users"))).scalar_one()
            managed_count = (
                await session.execute(text("SELECT count(*) FROM managed_services"))
            ).scalar_one()

        await engine.dispose()

        assert config_count >= 1, "system_config should have at least 1 row"
        assert profile_count >= 1, "microphone_profiles should have at least 1 row"
        assert user_count >= 1, "users should have at least 1 row"
        assert managed_count >= 1, "managed_services should have at least 1 row"


@pytest.mark.integration
class TestRunAllSeedersCloudSync:
    """Regression tests: run_all_seeders with cloud env vars.

    Verifies per-seeder transaction isolation resolves the historic
    duplicate-key bug (ConfigSeeder + CloudSyncSeeder both inserting
    ``cloud_sync`` key).
    """

    async def test_run_all_seeders_with_cloud_env_vars(
        self,
        postgres_container: PostgresContainer,
    ) -> None:
        """run_all_seeders succeeds when SILVASONIC_CLOUD_REMOTE_* vars are set.

        Regression: ConfigSeeder inserts cloud_sync with defaults, then
        CloudSyncSeeder UPSERTs with env-var credentials.  Both must
        coexist without IntegrityError.
        """
        from unittest.mock import patch as _patch

        from cryptography.fernet import Fernet
        from silvasonic.controller.seeder import run_all_seeders
        from silvasonic.core.database.models.system import SystemConfig

        key = Fernet.generate_key().decode()
        env = {
            "SILVASONIC_CLOUD_REMOTE_TYPE": "webdav",
            "SILVASONIC_CLOUD_REMOTE_URL": "https://example.com/remote.php/webdav/",
            "SILVASONIC_CLOUD_REMOTE_USER": "testuser",
            "SILVASONIC_CLOUD_REMOTE_PASS": "testpass",
            "SILVASONIC_ENCRYPTION_KEY": key,
        }

        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        async with session_factory() as session:
            with _patch.dict("os.environ", env):
                await run_all_seeders(session_factory)

        # Verify: cloud_sync exists with enabled=True and encrypted creds
        async with session_factory() as session:
            row = await session.get(SystemConfig, "cloud_sync")

        await engine.dispose()

        assert row is not None, "cloud_sync row must exist after seeding"
        assert row.value["enabled"] is True
        assert row.value["remote_type"] == "webdav"
        assert row.value["remote_config"]["user"].startswith("enc:")
        assert row.value["remote_config"]["pass"].startswith("enc:")

    async def test_run_all_seeders_without_cloud_env_vars(
        self,
        postgres_container: PostgresContainer,
    ) -> None:
        """run_all_seeders succeeds with default cloud_sync (no env vars).

        Baseline: ConfigSeeder inserts cloud_sync with enabled=false.
        CloudSyncSeeder does nothing without env vars.
        """
        from unittest.mock import patch as _patch

        from silvasonic.controller.seeder import run_all_seeders
        from silvasonic.core.database.models.system import SystemConfig

        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        # Ensure cloud env vars are NOT set
        env_clear = {
            "SILVASONIC_CLOUD_REMOTE_TYPE": "",
            "SILVASONIC_CLOUD_REMOTE_URL": "",
            "SILVASONIC_CLOUD_REMOTE_USER": "",
            "SILVASONIC_CLOUD_REMOTE_PASS": "",
        }

        with _patch.dict("os.environ", env_clear):
            await run_all_seeders(session_factory)

        # Verify: cloud_sync exists with defaults (enabled=false)
        async with session_factory() as session:
            row = await session.get(SystemConfig, "cloud_sync")

        await engine.dispose()

        assert row is not None, "cloud_sync row must exist after seeding"
        assert row.value["enabled"] is False
        assert row.value["remote_type"] is None

    async def test_run_all_seeders_idempotent_with_cloud_env(
        self,
        postgres_container: PostgresContainer,
    ) -> None:
        """Running run_all_seeders twice with cloud env vars is safe.

        Simulates a Controller restart: second run should UPSERT
        (not INSERT) the cloud_sync row without errors.
        """
        from unittest.mock import patch as _patch

        from cryptography.fernet import Fernet
        from silvasonic.controller.seeder import run_all_seeders
        from silvasonic.core.database.models.system import SystemConfig

        key = Fernet.generate_key().decode()
        env = {
            "SILVASONIC_CLOUD_REMOTE_TYPE": "webdav",
            "SILVASONIC_CLOUD_REMOTE_URL": "https://example.com/webdav/",
            "SILVASONIC_CLOUD_REMOTE_USER": "testuser",
            "SILVASONIC_CLOUD_REMOTE_PASS": "testpass",
            "SILVASONIC_ENCRYPTION_KEY": key,
        }

        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        # First run
        with _patch.dict("os.environ", env):
            await run_all_seeders(session_factory)

        # Second run (simulates restart)
        with _patch.dict("os.environ", env):
            await run_all_seeders(session_factory)

        # Verify single row, updated values
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT count(*) FROM system_config WHERE key = 'cloud_sync'")
            )
            count = result.scalar_one()
            row = await session.get(SystemConfig, "cloud_sync")

        await engine.dispose()

        assert count == 1, f"Expected exactly 1 cloud_sync row, got {count}"
        assert row is not None
        assert row.value["enabled"] is True


@pytest.mark.integration
class TestSeederIsolation:
    """Per-seeder transaction isolation with real DB.

    Verifies that a single seeder failure does not roll back
    successfully committed seeders.
    """

    async def test_partial_seeder_failure_commits_successful(
        self,
        postgres_container: PostgresContainer,
    ) -> None:
        """Failed seeder does not roll back other seeders' committed data."""
        from unittest.mock import patch as _patch

        from silvasonic.controller.seeder import run_all_seeders
        from silvasonic.core.database.models.system import SystemConfig

        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        # Patch ManagedServiceSeeder to crash
        with _patch(
            "silvasonic.controller.seeder.ManagedServiceSeeder.seed",
            side_effect=RuntimeError("boom"),
        ):
            failed = await run_all_seeders(session_factory)

        # ManagedServiceSeeder should be the only failure
        assert failed == ["managed_services"]

        # ConfigSeeder data must be committed (it ran before the crash)
        async with session_factory() as session:
            system_row = await session.get(SystemConfig, "system")
            assert system_row is not None, "ConfigSeeder data must persist"

        # ProfileBootstrapper data must be committed
        async with session_factory() as session:
            result = await session.execute(text("SELECT count(*) FROM microphone_profiles"))
            count = result.scalar_one()
            assert count >= 1, "ProfileBootstrapper data must persist"

        await engine.dispose()
