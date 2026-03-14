"""Unit tests for ConfigSeeder, ProfileBootstrapper, AuthSeeder, run_all_seeders.

Covers defaults insertion, skip-existing, Pydantic validation, YAML loading,
bcrypt hashing, and edge cases (missing files, invalid YAML, .gitkeep).
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.controller.seeder import (
    AuthSeeder,
    ConfigSeeder,
    ProfileBootstrapper,
    run_all_seeders,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------
def _make_defaults_yml(tmp_path: Path) -> Path:
    """Create a valid defaults.yml for testing."""
    yml = tmp_path / "defaults.yml"
    yml.write_text(
        """
system:
  latitude: 53.55
  longitude: 9.99
  max_recorders: 5
  max_uploaders: 3
  station_name: "Test Station"
  auto_enrollment: true

auth:
  default_username: "admin"
  default_password: "testpass"
""",
        encoding="utf-8",
    )
    return yml


def _make_profile_yml(tmp_path: Path) -> Path:
    """Create a valid profile YAML for testing."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    yml = profiles_dir / "test_mic.yml"
    yml.write_text(
        """
schema_version: "1.0"
slug: test_mic
name: Test Microphone
description: A test microphone profile.
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


def _make_invalid_profile_yml(tmp_path: Path) -> Path:
    """Create an invalid profile YAML (missing required fields)."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(exist_ok=True)
    yml = profiles_dir / "invalid.yml"
    yml.write_text(
        """
slug: invalid_mic
name: Invalid Microphone
# Missing audio section (required)
""",
        encoding="utf-8",
    )
    return profiles_dir


# ===================================================================
# ConfigSeeder
# ===================================================================


@pytest.mark.unit
class TestConfigSeeder:
    """Tests for the ConfigSeeder class."""

    async def test_seed_inserts_defaults(self, tmp_path: Path) -> None:
        """ConfigSeeder inserts system config defaults into empty DB."""
        yml = _make_defaults_yml(tmp_path)
        seeder = ConfigSeeder(defaults_path=yml)

        session = AsyncMock(add=MagicMock())
        session.get = AsyncMock(return_value=None)  # No existing values

        await seeder.seed(session)

        # Should have called session.add for "system" key
        assert session.add.call_count == 1
        added_obj = session.add.call_args[0][0]
        assert added_obj.key == "system"
        assert added_obj.value["station_name"] == "Test Station"
        assert added_obj.value["auto_enrollment"] is True

    async def test_seed_skips_existing_values(self, tmp_path: Path) -> None:
        """ConfigSeeder skips keys that already exist in DB."""
        yml = _make_defaults_yml(tmp_path)
        seeder = ConfigSeeder(defaults_path=yml)

        # Simulate existing "system" key
        existing = MagicMock()
        existing.key = "system"
        session = AsyncMock(add=MagicMock())
        session.get = AsyncMock(return_value=existing)

        await seeder.seed(session)

        # Should NOT have called session.add
        session.add.assert_not_called()

    async def test_seed_handles_missing_file(self, tmp_path: Path) -> None:
        """ConfigSeeder gracefully handles missing defaults.yml."""
        seeder = ConfigSeeder(defaults_path=tmp_path / "nonexistent.yml")
        session = AsyncMock(add=MagicMock())

        await seeder.seed(session)
        session.add.assert_not_called()

    async def test_seed_validates_against_pydantic(self, tmp_path: Path) -> None:
        """ConfigSeeder validates values against Pydantic schemas."""
        yml = tmp_path / "defaults.yml"
        yml.write_text(
            """
system:
  latitude: "not_a_float"
  longitude: 9.99
  max_recorders: 5
  max_uploaders: 3
  station_name: "Test"
  auto_enrollment: true
""",
            encoding="utf-8",
        )
        seeder = ConfigSeeder(defaults_path=yml)
        session = AsyncMock(add=MagicMock())

        await seeder.seed(session)

        # Invalid schema → skip (no add)
        session.add.assert_not_called()

    async def test_invalid_yaml_content(self, tmp_path: Path) -> None:
        """ConfigSeeder handles non-dict YAML content."""
        yml = tmp_path / "defaults.yml"
        yml.write_text("just a string\n", encoding="utf-8")
        seeder = ConfigSeeder(defaults_path=yml)
        session = AsyncMock(add=MagicMock())

        await seeder.seed(session)
        session.add.assert_not_called()

    async def test_unknown_key_without_schema(self, tmp_path: Path) -> None:
        """ConfigSeeder inserts keys without a schema mapping (no validation)."""
        yml = tmp_path / "defaults.yml"
        yml.write_text(
            """
custom_key:
  foo: bar
  baz: 42
""",
            encoding="utf-8",
        )
        seeder = ConfigSeeder(defaults_path=yml)
        session = AsyncMock(add=MagicMock())
        session.get = AsyncMock(return_value=None)

        await seeder.seed(session)

        assert session.add.call_count == 1
        added = session.add.call_args[0][0]
        assert added.key == "custom_key"


# ===================================================================
# ProfileBootstrapper
# ===================================================================


@pytest.mark.unit
class TestProfileBootstrapper:
    """Tests for the ProfileBootstrapper class."""

    async def test_seed_inserts_profile(self, tmp_path: Path) -> None:
        """ProfileBootstrapper inserts a valid YAML profile."""
        profiles_dir = _make_profile_yml(tmp_path)
        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)

        session = AsyncMock(add=MagicMock())
        session.get = AsyncMock(return_value=None)  # No existing profile

        await bootstrapper.seed(session)

        assert session.add.call_count == 1
        added = session.add.call_args[0][0]
        assert added.slug == "test_mic"
        assert added.name == "Test Microphone"
        assert added.is_system is True
        assert "audio" in added.config

    async def test_seed_skips_existing_profile(self, tmp_path: Path) -> None:
        """ProfileBootstrapper skips profiles that already exist."""
        profiles_dir = _make_profile_yml(tmp_path)
        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)

        existing = MagicMock()
        existing.slug = "test_mic"
        session = AsyncMock(add=MagicMock())
        session.get = AsyncMock(return_value=existing)

        await bootstrapper.seed(session)
        session.add.assert_not_called()

    async def test_seed_rejects_invalid_yaml(self, tmp_path: Path) -> None:
        """ProfileBootstrapper skips profiles that fail Pydantic validation."""
        profiles_dir = _make_invalid_profile_yml(tmp_path)
        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)
        session = AsyncMock(add=MagicMock())

        await bootstrapper.seed(session)
        session.add.assert_not_called()

    async def test_seed_no_directory(self, tmp_path: Path) -> None:
        """ProfileBootstrapper handles missing profiles directory."""
        bootstrapper = ProfileBootstrapper(profiles_dir=tmp_path / "nonexistent")
        session = AsyncMock(add=MagicMock())

        await bootstrapper.seed(session)
        session.add.assert_not_called()

    async def test_empty_profiles_dir(self, tmp_path: Path) -> None:
        """ProfileBootstrapper logs info when profiles directory is empty."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)
        session = AsyncMock(add=MagicMock())

        await bootstrapper.seed(session)
        session.add.assert_not_called()

    async def test_skips_gitkeep(self, tmp_path: Path) -> None:
        """ProfileBootstrapper ignores .gitkeep files."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / ".gitkeep").write_text("", encoding="utf-8")
        # Also add a valid profile so the "no_files" path doesn't match
        (profiles_dir / "valid.yml").write_text(
            """
schema_version: "1.0"
slug: valid_mic
name: Valid Mic
description: A valid mic.
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
        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)
        session = AsyncMock(add=MagicMock())
        session.get = AsyncMock(return_value=None)

        await bootstrapper.seed(session)

        # Only the valid profile should be inserted (not .gitkeep)
        assert session.add.call_count == 1
        added = session.add.call_args[0][0]
        assert added.slug == "valid_mic"

    async def test_yaml_parse_error(self, tmp_path: Path) -> None:
        """ProfileBootstrapper skips files with YAML parse errors."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "broken.yml").write_text(
            "invalid: yaml: [content: {broken",
            encoding="utf-8",
        )
        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)
        session = AsyncMock(add=MagicMock())

        await bootstrapper.seed(session)
        session.add.assert_not_called()

    async def test_missing_slug(self, tmp_path: Path) -> None:
        """ProfileBootstrapper skips profiles without a slug field."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "no_slug.yml").write_text(
            """
name: Missing Slug Mic
description: No slug field
audio:
  sample_rate: 48000
""",
            encoding="utf-8",
        )
        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)
        session = AsyncMock(add=MagicMock())

        await bootstrapper.seed(session)
        session.add.assert_not_called()


# ===================================================================
# AuthSeeder
# ===================================================================


@pytest.mark.unit
class TestAuthSeeder:
    """Tests for the AuthSeeder class."""

    async def test_seed_creates_admin(self, tmp_path: Path) -> None:
        """AuthSeeder creates default admin user with bcrypt hash."""
        yml = _make_defaults_yml(tmp_path)
        seeder = AuthSeeder(defaults_path=yml)

        # Mock: no existing user
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session = AsyncMock(add=MagicMock())
        session.execute = AsyncMock(return_value=result_mock)

        await seeder.seed(session)

        assert session.add.call_count == 1
        added = session.add.call_args[0][0]
        assert added.username == "admin"
        # Verify bcrypt hash format
        assert added.password_hash.startswith("$2")

    async def test_seed_skips_existing_user(self, tmp_path: Path) -> None:
        """AuthSeeder skips if admin user already exists."""
        yml = _make_defaults_yml(tmp_path)
        seeder = AuthSeeder(defaults_path=yml)

        existing = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing
        session = AsyncMock(add=MagicMock())
        session.execute = AsyncMock(return_value=result_mock)

        await seeder.seed(session)
        session.add.assert_not_called()

    async def test_missing_defaults_file(self, tmp_path: Path) -> None:
        """AuthSeeder gracefully handles missing defaults.yml."""
        seeder = AuthSeeder(defaults_path=tmp_path / "nonexistent.yml")
        session = AsyncMock(add=MagicMock())

        await seeder.seed(session)
        session.add.assert_not_called()

    async def test_no_auth_section(self, tmp_path: Path) -> None:
        """AuthSeeder skips when defaults.yml has no auth section."""
        yml = tmp_path / "defaults.yml"
        yml.write_text(
            """
system:
  latitude: 53.55
""",
            encoding="utf-8",
        )
        seeder = AuthSeeder(defaults_path=yml)
        session = AsyncMock(add=MagicMock())

        await seeder.seed(session)
        session.add.assert_not_called()

    async def test_invalid_yaml_content(self, tmp_path: Path) -> None:
        """AuthSeeder handles non-dict YAML content."""
        yml = tmp_path / "defaults.yml"
        yml.write_text("just a string\n", encoding="utf-8")
        seeder = AuthSeeder(defaults_path=yml)
        session = AsyncMock(add=MagicMock())

        await seeder.seed(session)
        session.add.assert_not_called()


# ===================================================================
# run_all_seeders
# ===================================================================


@pytest.mark.unit
class TestRunAllSeeders:
    """Tests for the run_all_seeders orchestration function."""

    async def test_calls_all_seeders_and_commits(self, tmp_path: Path) -> None:
        """run_all_seeders executes all 3 seeders and commits."""
        session = AsyncMock(add=MagicMock())
        session.get = AsyncMock(return_value=None)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        with (
            patch(
                "silvasonic.controller.seeder.ConfigSeeder.seed",
                new_callable=AsyncMock,
            ) as config_seed,
            patch(
                "silvasonic.controller.seeder.ProfileBootstrapper.seed",
                new_callable=AsyncMock,
            ) as profile_seed,
            patch(
                "silvasonic.controller.seeder.AuthSeeder.seed",
                new_callable=AsyncMock,
            ) as auth_seed,
        ):
            await run_all_seeders(session)

            config_seed.assert_called_once_with(session)
            profile_seed.assert_called_once_with(session)
            auth_seed.assert_called_once_with(session)
            session.commit.assert_called_once()
