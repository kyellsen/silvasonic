"""Unit tests for ConfigSeeder, ProfileBootstrapper, AuthSeeder, run_all_seeders.

Covers defaults insertion, skip-existing, Pydantic validation, YAML loading,
bcrypt hashing, edge cases (missing files, invalid YAML, .gitkeep), and
schema_map ↔ defaults.yml parity.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from silvasonic.controller.seeder import (
    AuthSeeder,
    ConfigSeeder,
    ProfileBootstrapper,
    _find_service_root,
    _get_config_dir,
    _get_defaults_yml,
    _get_profiles_dir,
    run_all_seeders,
)

# ===================================================================
# Path Resolvers (A4)
# ===================================================================


@pytest.mark.unit
class TestPathResolvers:
    """Tests for the @cache-decorated path resolver functions."""

    def test_find_service_root_finds_pyproject(self, tmp_path: Path) -> None:
        """_find_service_root walks up and finds pyproject.toml."""
        # Create: tmp_path/pyproject.toml  +  tmp_path/src/silvasonic/controller/
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
        deep = tmp_path / "src" / "silvasonic" / "controller"
        deep.mkdir(parents=True)

        result = _find_service_root(start=deep / "seeder.py")
        assert result == tmp_path

    def test_find_service_root_fallback(self, tmp_path: Path) -> None:
        """_find_service_root returns start.parent when no pyproject.toml found."""
        # No pyproject.toml anywhere — uses /tmp which has no pyproject.toml above
        leaf = tmp_path / "nowhere" / "deep" / "file.py"
        leaf.parent.mkdir(parents=True)

        result = _find_service_root(start=leaf)
        # Fallback: start.parent
        assert result == leaf.parent

    def test_get_config_dir(self) -> None:
        """_get_config_dir returns service_root/config."""
        _get_config_dir.cache_clear()
        try:
            with patch(
                "silvasonic.controller.seeder._find_service_root",
                return_value=Path("/fake/root"),
            ):
                result = _get_config_dir()
            assert result == Path("/fake/root/config")
        finally:
            _get_config_dir.cache_clear()

    def test_get_defaults_yml(self) -> None:
        """_get_defaults_yml returns config_dir/defaults.yml."""
        _get_defaults_yml.cache_clear()
        try:
            with patch(
                "silvasonic.controller.seeder._get_config_dir",
                return_value=Path("/fake/config"),
            ):
                result = _get_defaults_yml()
            assert result == Path("/fake/config/defaults.yml")
        finally:
            _get_defaults_yml.cache_clear()

    def test_get_profiles_dir(self) -> None:
        """_get_profiles_dir returns config_dir/profiles."""
        _get_profiles_dir.cache_clear()
        try:
            with patch(
                "silvasonic.controller.seeder._get_config_dir",
                return_value=Path("/fake/config"),
            ):
                result = _get_profiles_dir()
            assert result == Path("/fake/config/profiles")
        finally:
            _get_profiles_dir.cache_clear()


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------
def _make_defaults_yml(tmp_path: Path) -> Path:
    """Create a valid defaults.yml covering ALL seeder keys.

    Mirrors the real defaults.yml structure so that ConfigSeeder exercises
    every entry in its schema_map (system, processor, uploader, birdnet)
    plus the auth block handled by AuthSeeder.
    """
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

processor:
  janitor_threshold_warning: 70.0
  janitor_threshold_critical: 80.0
  janitor_threshold_emergency: 90.0
  janitor_interval_seconds: 60
  janitor_batch_size: 50
  indexer_poll_interval: 2.0

uploader:
  enabled: true
  poll_interval: 30
  bandwidth_limit: "1M"
  schedule_start_hour: 22
  schedule_end_hour: 6

birdnet:
  confidence_threshold: 0.25
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
        """ConfigSeeder inserts all schema_map keys from defaults.yml."""
        yml = _make_defaults_yml(tmp_path)
        seeder = ConfigSeeder(defaults_path=yml)

        session = AsyncMock(add=MagicMock())
        session.get = AsyncMock(return_value=None)  # No existing values

        await seeder.seed(session)

        # Should seed all 4 config keys (auth is handled by AuthSeeder)
        assert session.add.call_count == 4
        added_keys = {call[0][0].key for call in session.add.call_args_list}
        assert added_keys == {"system", "processor", "uploader", "birdnet"}

        # Spot-check specific values
        added_by_key = {call[0][0].key: call[0][0].value for call in session.add.call_args_list}
        assert added_by_key["system"]["station_name"] == "Test Station"
        assert added_by_key["processor"]["janitor_batch_size"] == 50
        assert added_by_key["uploader"]["bandwidth_limit"] == "1M"
        assert added_by_key["birdnet"]["confidence_threshold"] == 0.25

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

    async def test_generic_usb_profile_seeded(self) -> None:
        """Real generic_usb.yml is valid and seeds correctly."""
        from silvasonic.controller.seeder import _find_service_root

        profiles_dir = _find_service_root() / "config" / "profiles"
        assert (profiles_dir / "generic_usb.yml").exists(), "generic_usb.yml must exist"

        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)
        session = AsyncMock(add=MagicMock())
        session.get = AsyncMock(return_value=None)  # All profiles are new

        await bootstrapper.seed(session)

        # Should have inserted at least the generic_usb profile
        slugs = [call.args[0].slug for call in session.add.call_args_list]
        assert "generic_usb" in slugs, "generic_usb must be seeded"

        # Verify the generic_usb config content
        generic_calls = [c for c in session.add.call_args_list if c.args[0].slug == "generic_usb"]
        generic_db = generic_calls[0].args[0]
        assert generic_db.is_system is True
        assert generic_db.config["audio"]["sample_rate"] == 48000
        assert generic_db.config["audio"]["channels"] == 1
        assert generic_db.config["audio"]["format"] == "S16LE"
        assert generic_db.config["processing"]["gain_db"] == 0.0


@pytest.mark.unit
class TestAllRealProfilesValid:
    """Validate every .yml file in config/profiles/ against the Pydantic schema.

    This test ensures that new or modified seed profiles never silently fail
    Pydantic validation at Controller startup (which would cause them to be
    skipped without any test failure).
    """

    @staticmethod
    def _real_profiles_dir() -> Path:
        from silvasonic.controller.seeder import _find_service_root

        return _find_service_root() / "config" / "profiles"

    @staticmethod
    def _collect_profile_ids() -> list[str]:
        """Discover all .yml basenames for parametrize IDs."""
        from silvasonic.controller.seeder import _find_service_root

        d = _find_service_root() / "config" / "profiles"
        return sorted(p.name for p in d.glob("*.yml"))

    @pytest.mark.parametrize(
        "yml_name",
        _collect_profile_ids.__func__(),  # type: ignore[attr-defined]
        ids=lambda n: n.removesuffix(".yml"),
    )
    def test_profile_passes_pydantic_validation(self, yml_name: str) -> None:
        """Each seed YAML must parse without Pydantic ValidationError."""
        import yaml
        from silvasonic.core.schemas.devices import MicrophoneProfile

        yml_path = self._real_profiles_dir() / yml_name
        raw = yaml.safe_load(yml_path.read_text(encoding="utf-8"))

        assert isinstance(raw, dict), f"{yml_name}: YAML root must be a mapping"
        assert "slug" in raw, f"{yml_name}: missing required 'slug' field"

        # This will raise ValidationError on schema mismatch
        profile = MicrophoneProfile(**raw)

        # Basic sanity: slug and audio section must be present
        assert profile.slug, f"{yml_name}: slug must not be empty"
        assert profile.audio.sample_rate > 0, f"{yml_name}: sample_rate must be positive"

    @pytest.mark.parametrize(
        "yml_name",
        _collect_profile_ids.__func__(),  # type: ignore[attr-defined]
        ids=lambda n: n.removesuffix(".yml"),
    )
    async def test_profile_seeds_to_db(self, yml_name: str) -> None:
        """Each seed YAML must be accepted by ProfileBootstrapper (full pipeline)."""
        profiles_dir = self._real_profiles_dir()
        # Create a temporary dir with only this one profile
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp) / "profiles"
            tmp_dir.mkdir()
            shutil.copy2(profiles_dir / yml_name, tmp_dir / yml_name)

            bootstrapper = ProfileBootstrapper(profiles_dir=tmp_dir)
            session = AsyncMock(add=MagicMock())
            session.get = AsyncMock(return_value=None)

            await bootstrapper.seed(session)

            assert session.add.call_count == 1, (
                f"{yml_name}: ProfileBootstrapper must insert exactly 1 profile, "
                f"got {session.add.call_count} (likely a validation failure)"
            )


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

        # Mock bcrypt to avoid ~200ms CPU-intensive hashing in unit tests.
        # Real bcrypt behaviour is covered by integration tests.
        with patch(
            "silvasonic.controller.seeder.bcrypt.hashpw",
            return_value=b"$2b$12$mockhashvalue",
        ):
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

            config_seed.assert_called_once()
            profile_seed.assert_called_once_with(session)
            auth_seed.assert_called_once()
            session.commit.assert_called_once()


# ===================================================================
# Defaults YAML ↔ Schema Parity (Drift Guard)
# ===================================================================


@pytest.mark.unit
class TestDefaultsYamlParity:
    """Ensure the real defaults.yml stays in sync with the seeder's schema_map.

    These tests catch three classes of drift:
    1. A key added to defaults.yml but missing from schema_map (would be
       seeded without validation).
    2. A key added to schema_map but missing from defaults.yml (would
       never be seeded).
    3. A YAML value that no longer passes Pydantic validation (typo in
       defaults.yml, schema field renamed, etc.).
    """

    @staticmethod
    def _load_real_defaults() -> dict[str, Any]:
        """Load the real config/defaults.yml from the service tree."""
        config_dir = Path(__file__).resolve().parents[2] / "config"
        defaults_path = config_dir / "defaults.yml"
        assert defaults_path.exists(), f"defaults.yml not found at {defaults_path}"
        with defaults_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        return data

    @staticmethod
    def _get_schema_map() -> dict[str, type]:
        """Return the same schema_map the seeder uses at runtime."""
        from silvasonic.core.config_schemas import (
            BirdnetSettings,
            ProcessorSettings,
            SystemSettings,
            UploaderSettings,
        )

        return {
            "system": SystemSettings,
            "processor": ProcessorSettings,
            "uploader": UploaderSettings,
            "birdnet": BirdnetSettings,
        }

    def test_yaml_keys_covered_by_schema_map(self) -> None:
        """Every config key in defaults.yml (except 'auth') has a schema_map entry."""
        defaults = self._load_real_defaults()
        schema_map = self._get_schema_map()
        yaml_config_keys = {k for k in defaults if k != "auth"}
        missing = yaml_config_keys - set(schema_map)
        assert not missing, f"YAML keys without schema_map entry: {missing}"

    def test_schema_map_keys_present_in_yaml(self) -> None:
        """Every schema_map key has a corresponding section in defaults.yml."""
        defaults = self._load_real_defaults()
        schema_map = self._get_schema_map()
        missing = set(schema_map) - set(defaults)
        assert not missing, f"schema_map keys missing from defaults.yml: {missing}"

    def test_all_yaml_values_pass_pydantic_validation(self) -> None:
        """Every YAML section validates against its Pydantic schema."""
        defaults = self._load_real_defaults()
        schema_map = self._get_schema_map()
        for key, schema_cls in schema_map.items():
            section = defaults.get(key)
            assert section is not None, f"Section '{key}' missing from defaults.yml"
            # This will raise ValidationError if the values don't match the schema
            instance = schema_cls(**section)
            # Round-trip: ensure model_dump matches the original YAML values
            dumped = instance.model_dump()
            for field_name, yaml_value in section.items():
                assert dumped[field_name] == yaml_value, (
                    f"Pydantic default mismatch for {key}.{field_name}: "
                    f"YAML={yaml_value!r}, schema={dumped[field_name]!r}"
                )
