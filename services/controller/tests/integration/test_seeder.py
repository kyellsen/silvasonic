"""Integration tests: Seeders ↔ real station database (SQLite).

Verifies that ConfigSeeder, ProfileBootstrapper, ModuleSeeder and AuthSeeder
actually insert data into a real station database file.

Uses the shared ``station_db`` fixture from ``silvasonic-test-utils``
(surfaced via root ``conftest.py``).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from silvasonic.controller.seeder import (
    AuthSeeder,
    ConfigSeeder,
    ModuleSeeder,
    ProfileBootstrapper,
)
from silvasonic.core.database.models.system import Module, SettingsSection
from silvasonic.core.database.session import create_station_engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _make_defaults_yml(tmp_path: Path) -> Path:
    """Create a valid defaults.yml for integration testing."""
    yml = tmp_path / "defaults.yml"
    yml.write_text(
        """
station:
  name: "Integration Test Station"
  latitude: null
  longitude: null

recording:
  auto_enrollment: true
  max_microphones: 5

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
schema_version: "2.0"
slug: integration_mic
name: Integration Test Microphone
description: A profile for integration testing.
audio:
  sample_rate_hz: 48000
  channels: 1
  sample_format: S16LE
processing:
  gain_db: 0.0
  chunk_frames: 4096
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
    """Verify ConfigSeeder inserts actual rows into a real station database."""

    async def test_seed_inserts_settings(
        self,
        tmp_path: Path,
        station_db: Path,
    ) -> None:
        """ConfigSeeder inserts the station and recording sections into settings."""
        engine = create_station_engine(station_db)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        yml = _make_defaults_yml(tmp_path)
        seeder = ConfigSeeder(defaults_path=yml)

        async with session_factory() as session:
            await seeder.seed(session)
            await session.commit()

        # Verify the row exists in the real DB
        async with session_factory() as session:
            station = (
                await session.execute(
                    text("SELECT value, revision FROM settings WHERE section = 'station'")
                )
            ).one_or_none()
            recording = (
                await session.execute(
                    text("SELECT value FROM settings WHERE section = 'recording'")
                )
            ).scalar_one_or_none()

        await engine.dispose()

        assert station is not None, "station section not found after seeding"
        station = (json.loads(station[0]), station[1])  # raw SQL: JSON is TEXT in SQLite
        assert station[0]["name"] == "Integration Test Station"
        assert station[1] == 1, "revision starts at 1"
        assert recording is not None, "recording section not found after seeding"
        recording = json.loads(recording)
        assert recording["auto_enrollment"] is True
        assert recording["max_microphones"] == 5

    async def test_station_id_is_uuidv7_and_kept(
        self,
        tmp_path: Path,
        station_db: Path,
    ) -> None:
        """The station gets a UUIDv7 id once; a second seeding keeps it."""
        engine = create_station_engine(station_db)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        seeder = ConfigSeeder(defaults_path=_make_defaults_yml(tmp_path))
        query = text("SELECT value ->> 'id' FROM settings WHERE section = 'station'")

        async with session_factory() as session:
            await seeder.seed(session)
            await session.commit()
        async with session_factory() as session:
            first_id = (await session.execute(query)).scalar_one()

        async with session_factory() as session:
            await seeder.seed(session)
            await session.commit()
        async with session_factory() as session:
            second_id = (await session.execute(query)).scalar_one()

        await engine.dispose()

        assert first_id is not None
        assert uuid.UUID(first_id).version == 7
        assert second_id == first_id, "station.id must never be overwritten"

    async def test_seed_is_idempotent(
        self,
        tmp_path: Path,
        station_db: Path,
    ) -> None:
        """Running ConfigSeeder twice does not create duplicate rows."""
        engine = create_station_engine(station_db)
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
                text("SELECT count(*) FROM settings WHERE section = 'station'")
            )
            count = result.scalar_one()

        await engine.dispose()

        assert count == 1, f"Expected 1 row, got {count}"


@pytest.mark.integration
class TestProfileBootstrapperIntegration:
    """Verify ProfileBootstrapper inserts actual profiles into a real station database."""

    async def test_seed_inserts_profile(
        self,
        tmp_path: Path,
        station_db: Path,
    ) -> None:
        """ProfileBootstrapper inserts a profile row into microphone_profiles table."""
        engine = create_station_engine(station_db)
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
                    "SELECT name, built_in FROM microphone_profiles WHERE slug = 'integration_mic'"
                )
            )
            row = result.one_or_none()

        await engine.dispose()

        assert row is not None, "microphone_profiles row not found after seeding"
        assert row[0] == "Integration Test Microphone"
        assert row[1] == 1  # built_in (raw SQL: booleans are 0/1)


@pytest.mark.integration
class TestAuthSeederIntegration:
    """Verify AuthSeeder creates an admin user in a real station database."""

    async def test_seed_creates_admin_with_bcrypt(
        self,
        tmp_path: Path,
        station_db: Path,
    ) -> None:
        """AuthSeeder inserts an admin user with bcrypt-hashed password."""
        engine = create_station_engine(station_db)
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
        station_db: Path,
    ) -> None:
        """Seeders populate settings, microphone_profiles, modules, and users."""
        engine = create_station_engine(station_db)
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
            await ModuleSeeder().seed(session)
            await session.commit()

        # Verify all tables have data
        async with session_factory() as session:
            settings_count = (
                await session.execute(text("SELECT count(*) FROM settings"))
            ).scalar_one()
            profile_count = (
                await session.execute(text("SELECT count(*) FROM microphone_profiles"))
            ).scalar_one()
            user_count = (await session.execute(text("SELECT count(*) FROM users"))).scalar_one()
            modules = dict(
                (await session.execute(text("SELECT id, enabled FROM modules"))).tuples().all()
            )

        await engine.dispose()

        assert settings_count >= 1, "settings should have at least 1 row"
        assert profile_count >= 1, "microphone_profiles should have at least 1 row"
        assert user_count >= 1, "users should have at least 1 row"
        assert modules == {"birdnet": True, "cloud_sync": False}


@pytest.mark.integration
class TestRunAllSeedersCloudSync:
    """Regression tests: run_all_seeders with cloud env vars.

    Verifies per-seeder transaction isolation resolves the historic
    duplicate-key bug (ConfigSeeder + CloudSyncSeeder both inserting
    the ``sync`` section).
    """

    async def test_run_all_seeders_with_cloud_env_vars(
        self,
        station_db: Path,
    ) -> None:
        """run_all_seeders succeeds when SILVASONIC_CLOUD_REMOTE_* vars are set.

        Regression: ConfigSeeder inserts the sync section with defaults, then
        CloudSyncSeeder UPSERTs with env-var credentials.  Both must
        coexist without IntegrityError.
        """
        from unittest.mock import patch as _patch

        from cryptography.fernet import Fernet
        from silvasonic.controller.seeder import run_all_seeders

        key = Fernet.generate_key().decode()
        env = {
            "SILVASONIC_CLOUD_REMOTE_TYPE": "webdav",
            "SILVASONIC_CLOUD_REMOTE_URL": "https://example.com/remote.php/webdav/",
            "SILVASONIC_CLOUD_REMOTE_USER": "testuser",
            "SILVASONIC_CLOUD_REMOTE_PASS": "testpass",
            "SILVASONIC_ENCRYPTION_KEY": key,
        }

        engine = create_station_engine(station_db)
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        async with session_factory() as session:
            with _patch.dict("os.environ", env):
                await run_all_seeders(session_factory)

        # Verify: sync section has encrypted creds and the module is switched on
        async with session_factory() as session:
            row = await session.get(SettingsSection, "sync")
            module = await session.get(Module, "cloud_sync")

        await engine.dispose()

        assert row is not None, "sync section must exist after seeding"
        assert "enabled" not in row.value
        assert module is not None and module.enabled is True
        assert row.value["remote_type"] == "webdav"
        assert row.value["remote_config"]["user"].startswith("enc:")
        assert row.value["remote_config"]["pass"].startswith("enc:")

    async def test_run_all_seeders_without_cloud_env_vars(
        self,
        station_db: Path,
    ) -> None:
        """run_all_seeders succeeds with the default sync section (no env vars).

        Baseline: ConfigSeeder inserts the sync section, ModuleSeeder the
        cloud_sync module switched off. CloudSyncSeeder does nothing
        without env vars.
        """
        from unittest.mock import patch as _patch

        from silvasonic.controller.seeder import run_all_seeders

        engine = create_station_engine(station_db)
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

        # Verify: sync section exists with defaults, module switched off
        async with session_factory() as session:
            row = await session.get(SettingsSection, "sync")
            module = await session.get(Module, "cloud_sync")

        await engine.dispose()

        assert row is not None, "sync section must exist after seeding"
        assert module is not None and module.enabled is False
        assert row.value["remote_type"] is None

    async def test_run_all_seeders_idempotent_with_cloud_env(
        self,
        station_db: Path,
    ) -> None:
        """Running run_all_seeders twice with cloud env vars is safe.

        Simulates a Controller restart: second run should UPSERT
        (not INSERT) the sync section without errors; the database trigger
        increments its revision on every write.
        """
        from unittest.mock import patch as _patch

        from cryptography.fernet import Fernet
        from silvasonic.controller.seeder import run_all_seeders

        key = Fernet.generate_key().decode()
        env = {
            "SILVASONIC_CLOUD_REMOTE_TYPE": "webdav",
            "SILVASONIC_CLOUD_REMOTE_URL": "https://example.com/webdav/",
            "SILVASONIC_CLOUD_REMOTE_USER": "testuser",
            "SILVASONIC_CLOUD_REMOTE_PASS": "testpass",
            "SILVASONIC_ENCRYPTION_KEY": key,
        }

        engine = create_station_engine(station_db)
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
                text("SELECT count(*) FROM settings WHERE section = 'sync'")
            )
            count = result.scalar_one()
            row = await session.get(SettingsSection, "sync")
            module = await session.get(Module, "cloud_sync")

        await engine.dispose()

        assert count == 1, f"Expected exactly 1 sync section, got {count}"
        assert row is not None
        # Inserted (1), then updated by the first and the second CloudSyncSeeder run
        assert row.revision == 3
        assert module is not None and module.enabled is True


@pytest.mark.integration
class TestSeederIsolation:
    """Per-seeder transaction isolation with real DB.

    Verifies that a single seeder failure does not roll back
    successfully committed seeders.
    """

    async def test_partial_seeder_failure_commits_successful(
        self,
        station_db: Path,
    ) -> None:
        """Failed seeder does not roll back other seeders' committed data."""
        from unittest.mock import patch as _patch

        from silvasonic.controller.seeder import run_all_seeders

        engine = create_station_engine(station_db)
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        # Patch ModuleSeeder to crash
        with _patch(
            "silvasonic.controller.seeder.ModuleSeeder.seed",
            side_effect=RuntimeError("boom"),
        ):
            failed = await run_all_seeders(session_factory)

        # ModuleSeeder should be the only failure
        assert failed == ["modules"]

        # ConfigSeeder data must be committed (it ran before the crash)
        async with session_factory() as session:
            station_row = await session.get(SettingsSection, "station")
            assert station_row is not None, "ConfigSeeder data must persist"

        # ProfileBootstrapper data must be committed
        async with session_factory() as session:
            result = await session.execute(text("SELECT count(*) FROM microphone_profiles"))
            count = result.scalar_one()
            assert count >= 1, "ProfileBootstrapper data must persist"

        await engine.dispose()
