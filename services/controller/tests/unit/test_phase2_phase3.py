"""Unit tests for Phase 2 (Seeders) and Phase 3 (Container Lifecycle).

Covers:
- ConfigSeeder: defaults insertion, skip-existing, Pydantic validation
- ProfileBootstrapper: YAML loading, validation, skip-existing, is_system flag
- AuthSeeder: bcrypt hashing, skip-existing
- Tier2ServiceSpec: field validation, build_recorder_spec factory
- ContainerManager: start/stop/remove/reconcile with mocked Podman
- ReconciliationLoop: trigger, reconcile_once
- NudgeSubscriber: process "reconcile" message
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Phase 3 — Container Lifecycle
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import (
    MountSpec,
    Tier2ServiceSpec,
    build_recorder_spec,
)
from silvasonic.controller.nudge_subscriber import NudgeSubscriber
from silvasonic.controller.reconciler import (
    DeviceStateEvaluator,
    ReconciliationLoop,
)

# Phase 2 — Seeders
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


def _make_spec(**overrides: Any) -> Tier2ServiceSpec:
    """Create a minimal Tier2ServiceSpec for testing."""
    defaults: dict[str, Any] = {
        "image": "silvasonic-recorder:latest",
        "name": "silvasonic-recorder-test",
        "network": "silvasonic-net",
        "memory_limit": "512m",
        "cpu_limit": 1.0,
        "oom_score_adj": -999,
        "labels": {
            "io.silvasonic.tier": "2",
            "io.silvasonic.owner": "controller",
            "io.silvasonic.service": "recorder",
        },
    }
    defaults.update(overrides)
    return Tier2ServiceSpec(**defaults)


# ===================================================================
# Phase 2 — Seeders
# ===================================================================


@pytest.mark.unit
class TestConfigSeeder:
    async def test_seed_inserts_defaults(self, tmp_path: Path) -> None:
        """ConfigSeeder inserts system config defaults into empty DB."""
        yml = _make_defaults_yml(tmp_path)
        seeder = ConfigSeeder(defaults_path=yml)

        session = AsyncMock()
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
        session = AsyncMock()
        session.get = AsyncMock(return_value=existing)

        await seeder.seed(session)

        # Should NOT have called session.add
        session.add.assert_not_called()

    async def test_seed_handles_missing_file(self, tmp_path: Path) -> None:
        """ConfigSeeder gracefully handles missing defaults.yml."""
        seeder = ConfigSeeder(defaults_path=tmp_path / "nonexistent.yml")
        session = AsyncMock()

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
        session = AsyncMock()

        await seeder.seed(session)

        # Invalid schema → skip (no add)
        session.add.assert_not_called()


@pytest.mark.unit
class TestProfileBootstrapper:
    async def test_seed_inserts_profile(self, tmp_path: Path) -> None:
        """ProfileBootstrapper inserts a valid YAML profile."""
        profiles_dir = _make_profile_yml(tmp_path)
        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)

        session = AsyncMock()
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
        session = AsyncMock()
        session.get = AsyncMock(return_value=existing)

        await bootstrapper.seed(session)
        session.add.assert_not_called()

    async def test_seed_rejects_invalid_yaml(self, tmp_path: Path) -> None:
        """ProfileBootstrapper skips profiles that fail Pydantic validation."""
        profiles_dir = _make_invalid_profile_yml(tmp_path)
        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)
        session = AsyncMock()

        await bootstrapper.seed(session)
        session.add.assert_not_called()

    async def test_seed_no_directory(self, tmp_path: Path) -> None:
        """ProfileBootstrapper handles missing profiles directory."""
        bootstrapper = ProfileBootstrapper(profiles_dir=tmp_path / "nonexistent")
        session = AsyncMock()

        await bootstrapper.seed(session)
        session.add.assert_not_called()


@pytest.mark.unit
class TestAuthSeeder:
    async def test_seed_creates_admin(self, tmp_path: Path) -> None:
        """AuthSeeder creates default admin user with bcrypt hash."""
        yml = _make_defaults_yml(tmp_path)
        seeder = AuthSeeder(defaults_path=yml)

        # Mock: no existing user
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session = AsyncMock()
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
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        await seeder.seed(session)
        session.add.assert_not_called()


@pytest.mark.unit
class TestRunAllSeeders:
    async def test_calls_all_seeders_and_commits(self, tmp_path: Path) -> None:
        """run_all_seeders executes all 3 seeders and commits."""
        session = AsyncMock()
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


# ===================================================================
# Phase 3 — Container Spec
# ===================================================================


@pytest.mark.unit
class TestTier2ServiceSpec:
    def test_valid_spec(self) -> None:
        """Tier2ServiceSpec validates with all required fields."""
        spec = _make_spec()
        assert spec.image == "silvasonic-recorder:latest"
        assert spec.memory_limit == "512m"
        assert spec.oom_score_adj == -999

    def test_default_restart_policy(self) -> None:
        """Default restart policy is on-failure with max 5 retries."""
        spec = _make_spec()
        assert spec.restart_policy.name == "on-failure"
        assert spec.restart_policy.max_retry_count == 5

    def test_mount_spec(self) -> None:
        """MountSpec creates correct mount configuration."""
        mount = MountSpec(source="/host/path", target="/container/path", read_only=True)
        assert mount.source == "/host/path"
        assert mount.read_only is True

    def test_missing_required_field_raises(self) -> None:
        """Tier2ServiceSpec raises ValidationError without required fields."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Tier2ServiceSpec(image="test:latest", name="test")  # type: ignore[call-arg]


@pytest.mark.unit
class TestBuildRecorderSpec:
    def test_build_recorder_spec(self) -> None:
        """build_recorder_spec creates a valid spec from Device + Profile."""
        device = MagicMock()
        device.name = "ultramic-01"
        device.config = {"alsa_device": "hw:2,0"}

        profile = MagicMock()
        profile.slug = "ultramic_384_evo"

        spec = build_recorder_spec(device, profile)

        assert spec.name == "silvasonic-recorder-ultramic-01"
        assert spec.image == "silvasonic-recorder:latest"
        assert spec.environment["RECORDER_DEVICE"] == "hw:2,0"
        assert spec.environment["RECORDER_PROFILE"] == "ultramic_384_evo"
        assert spec.labels["io.silvasonic.service"] == "recorder"
        assert spec.labels["io.silvasonic.device_id"] == "ultramic-01"
        assert spec.oom_score_adj == -999  # Protected
        assert spec.privileged is True
        assert len(spec.devices) == 1


# ===================================================================
# Phase 3 — Container Manager
# ===================================================================


@pytest.mark.unit
class TestContainerManager:
    def test_start_not_connected(self) -> None:
        """start() returns None when Podman is not connected."""
        client = MagicMock()
        client.is_connected = False
        mgr = ContainerManager(client)

        result = mgr.start(_make_spec())
        assert result is None

    def test_start_creates_container(self) -> None:
        """start() calls containers.run() with correct params."""
        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_container.name = "silvasonic-recorder-test"
        mock_container.status = "running"
        mock_container.labels = {}

        client = MagicMock()
        client.is_connected = True
        client.containers.run.return_value = mock_container
        client.containers.get.side_effect = Exception("not found")

        mgr = ContainerManager(client)
        result = mgr.start(_make_spec())

        assert result is not None
        assert result["name"] == "silvasonic-recorder-test"
        client.containers.run.assert_called_once()

    def test_start_skips_existing(self) -> None:
        """start() returns existing container info if already running."""
        existing = MagicMock()
        existing.id = "abc123"
        existing.name = "silvasonic-recorder-test"
        existing.status = "running"
        existing.labels = {}

        client = MagicMock()
        client.is_connected = True
        client.containers.get.return_value = existing

        mgr = ContainerManager(client)
        result = mgr.start(_make_spec())

        assert result is not None
        client.containers.run.assert_not_called()

    def test_stop_sends_sigterm(self) -> None:
        """stop() stops a container by name."""
        client = MagicMock()
        client.is_connected = True
        mgr = ContainerManager(client)

        result = mgr.stop("test-container", timeout=5)
        assert result is True
        client.containers.get.return_value.stop.assert_called_once_with(timeout=5)

    def test_stop_not_connected(self) -> None:
        """stop() returns False when Podman is not connected."""
        client = MagicMock()
        client.is_connected = False
        mgr = ContainerManager(client)

        result = mgr.stop("test-container")
        assert result is False

    def test_remove_force_removes(self) -> None:
        """remove() force-removes a container."""
        client = MagicMock()
        client.is_connected = True
        mgr = ContainerManager(client)

        result = mgr.remove("test-container")
        assert result is True

    def test_stop_not_found_returns_true(self) -> None:
        """stop() returns True when container is already gone (NotFound)."""
        from podman.errors import NotFound

        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = NotFound("gone")
        mgr = ContainerManager(client)

        result = mgr.stop("vanished-container")
        assert result is True

    def test_remove_not_found_returns_true(self) -> None:
        """remove() returns True when container is already gone (NotFound)."""
        from podman.errors import NotFound

        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = NotFound("gone")
        mgr = ContainerManager(client)

        result = mgr.remove("vanished-container")
        assert result is True

    def test_get_not_found_returns_none(self) -> None:
        """get() returns None silently when container does not exist."""
        from podman.errors import NotFound

        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = NotFound("no such container")
        mgr = ContainerManager(client)

        result = mgr.get("nonexistent")
        assert result is None

    def test_get_other_exception_returns_none(self) -> None:
        """get() returns None and logs warning on unexpected errors."""
        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = ConnectionError("socket gone")
        mgr = ContainerManager(client)

        result = mgr.get("broken")
        assert result is None

    def test_reconcile_starts_missing_and_stops_orphaned(self) -> None:
        """reconcile() starts missing containers and stops orphaned ones."""
        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = Exception("not found")

        mock_container = MagicMock()
        mock_container.id = "new123"
        mock_container.name = "silvasonic-recorder-new"
        mock_container.status = "running"
        mock_container.labels = {}
        client.containers.run.return_value = mock_container

        mgr = ContainerManager(client)

        desired = [_make_spec(name="silvasonic-recorder-new")]
        actual: list[dict[str, object]] = [
            {"name": "silvasonic-recorder-orphan", "status": "running"},
        ]

        mgr.reconcile(desired, actual)

        # Should start "new" and stop "orphan"
        client.containers.run.assert_called_once()
        assert client.containers.get.call_count >= 1

    def test_stop_connection_error_returns_false(self) -> None:
        """stop() returns False on ConnectionError (not silently swallowed)."""
        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = ConnectionError("socket gone")
        mgr = ContainerManager(client)

        assert mgr.stop("unreachable-container") is False


# ===================================================================
# Phase 3 — Reconciler
# ===================================================================


@pytest.mark.unit
class TestDeviceStateEvaluator:
    async def test_evaluate_eligible_device(self) -> None:
        """evaluate() returns specs for eligible devices."""
        device = MagicMock()
        device.name = "mic-01"
        device.status = "online"
        device.enabled = True
        device.enrollment_status = "enrolled"
        device.profile_slug = "test_profile"
        device.config = {"alsa_device": "hw:1,0"}

        profile = MagicMock()
        profile.slug = "test_profile"

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [device]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)
        session.get = AsyncMock(return_value=profile)

        evaluator = DeviceStateEvaluator()
        specs = await evaluator.evaluate(session)

        assert len(specs) == 1
        assert specs[0].name == "silvasonic-recorder-mic-01"

    async def test_evaluate_no_eligible_devices(self) -> None:
        """evaluate() returns empty list when no devices match criteria."""
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        evaluator = DeviceStateEvaluator()
        specs = await evaluator.evaluate(session)

        assert len(specs) == 0

    async def test_evaluate_missing_profile(self) -> None:
        """evaluate() skips device when linked profile is missing."""
        device = MagicMock()
        device.name = "mic-02"
        device.profile_slug = "nonexistent"
        device.config = {}

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [device]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)
        session.get = AsyncMock(return_value=None)  # Profile not found

        evaluator = DeviceStateEvaluator()
        specs = await evaluator.evaluate(session)

        assert len(specs) == 0


@pytest.mark.unit
class TestReconciliationLoop:
    def test_trigger_sets_event(self) -> None:
        """trigger() sets the asyncio Event for immediate reconciliation."""
        mgr = MagicMock()
        loop = ReconciliationLoop(mgr, interval=30.0)

        assert not loop._trigger_event.is_set()
        loop.trigger()
        assert loop._trigger_event.is_set()

    async def test_reconcile_once(self) -> None:
        """_reconcile_once() calls evaluate and reconcile."""
        mgr = MagicMock()
        mgr.list_managed.return_value = []
        mgr.reconcile = MagicMock()

        reconciler = ReconciliationLoop(mgr, interval=1.0)

        with (
            patch.object(
                reconciler._evaluator,
                "evaluate",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_session,
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()
            await reconciler._reconcile_once()


# ===================================================================
# Phase 3 — Nudge Subscriber
# ===================================================================


@pytest.mark.unit
class TestNudgeSubscriber:
    def test_init(self) -> None:
        """NudgeSubscriber initializes with reconciler and redis_url."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler, redis_url="redis://test:6379/0")
        assert sub._redis_url == "redis://test:6379/0"
        assert sub._reconciler is reconciler

    def test_handle_reconcile_triggers(self) -> None:
        """_handle_message() triggers reconciliation on 'reconcile' payload."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)

        sub._handle_message({"type": "message", "data": b"reconcile"})
        reconciler.trigger.assert_called_once()

    def test_handle_subscribe_ignored(self) -> None:
        """_handle_message() ignores non-message types (e.g. 'subscribe')."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)

        sub._handle_message({"type": "subscribe", "data": b"silvasonic:nudge"})
        reconciler.trigger.assert_not_called()

    def test_handle_unknown_payload_ignored(self) -> None:
        """_handle_message() ignores unknown message payloads."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)

        sub._handle_message({"type": "message", "data": b"restart"})
        reconciler.trigger.assert_not_called()

    def test_handle_string_data(self) -> None:
        """_handle_message() handles string data (not bytes)."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)

        sub._handle_message({"type": "message", "data": "reconcile"})
        reconciler.trigger.assert_called_once()

    async def test_run_reconnects_on_error(self) -> None:
        """run() reconnects automatically after Redis disconnection."""
        import asyncio

        import redis.asyncio as aioredis

        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler, redis_url="redis://fake:6379/0")

        call_count = 0

        def fake_from_url(url: str, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError
            raise ConnectionError("Redis unavailable")

        with (
            patch.object(aioredis, "from_url", side_effect=fake_from_url),
            patch(
                "silvasonic.controller.nudge_subscriber.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await sub.run()

        assert call_count >= 2


# ===================================================================
# Additional Coverage — Seeder Edge Cases
# ===================================================================


@pytest.mark.unit
class TestConfigSeederEdgeCases:
    async def test_invalid_yaml_content(self, tmp_path: Path) -> None:
        """ConfigSeeder handles non-dict YAML content."""
        yml = tmp_path / "defaults.yml"
        yml.write_text("just a string\n", encoding="utf-8")
        seeder = ConfigSeeder(defaults_path=yml)
        session = AsyncMock()

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
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        await seeder.seed(session)

        assert session.add.call_count == 1
        added = session.add.call_args[0][0]
        assert added.key == "custom_key"


@pytest.mark.unit
class TestProfileBootstrapperEdgeCases:
    async def test_empty_profiles_dir(self, tmp_path: Path) -> None:
        """ProfileBootstrapper logs info when profiles directory is empty."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)
        session = AsyncMock()

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
        session = AsyncMock()
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
        session = AsyncMock()

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
        session = AsyncMock()

        await bootstrapper.seed(session)
        session.add.assert_not_called()


@pytest.mark.unit
class TestAuthSeederEdgeCases:
    async def test_missing_defaults_file(self, tmp_path: Path) -> None:
        """AuthSeeder gracefully handles missing defaults.yml."""
        seeder = AuthSeeder(defaults_path=tmp_path / "nonexistent.yml")
        session = AsyncMock()

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
        session = AsyncMock()

        await seeder.seed(session)
        session.add.assert_not_called()

    async def test_invalid_yaml_content(self, tmp_path: Path) -> None:
        """AuthSeeder handles non-dict YAML content."""
        yml = tmp_path / "defaults.yml"
        yml.write_text("just a string\n", encoding="utf-8")
        seeder = AuthSeeder(defaults_path=yml)
        session = AsyncMock()

        await seeder.seed(session)
        session.add.assert_not_called()


# ===================================================================
# Additional Coverage — Container Manager Edge Cases
# ===================================================================


@pytest.mark.unit
class TestContainerManagerEdgeCases:
    def test_start_exception_returns_none(self) -> None:
        """start() returns None on unexpected exceptions."""
        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = Exception("not found")
        client.containers.run.side_effect = RuntimeError("image not found")
        mgr = ContainerManager(client)

        result = mgr.start(_make_spec())
        assert result is None

    def test_remove_not_connected_returns_false(self) -> None:
        """remove() returns False when Podman is not connected."""
        client = MagicMock()
        client.is_connected = False
        mgr = ContainerManager(client)

        assert mgr.remove("test-container") is False

    def test_remove_unexpected_error_returns_false(self) -> None:
        """remove() returns False on unexpected exceptions."""
        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = ConnectionError("socket gone")
        mgr = ContainerManager(client)

        assert mgr.remove("test-container") is False

    def test_list_managed_delegates(self) -> None:
        """list_managed() delegates to podman_client.list_managed_containers()."""
        client = MagicMock()
        client.list_managed_containers.return_value = [{"name": "test"}]
        mgr = ContainerManager(client)

        result = mgr.list_managed()
        assert result == [{"name": "test"}]
        client.list_managed_containers.assert_called_once()

    def test_get_not_connected_returns_none(self) -> None:
        """get() returns None when Podman is not connected."""
        client = MagicMock()
        client.is_connected = False
        mgr = ContainerManager(client)

        assert mgr.get("test") is None


# ===================================================================
# Additional Coverage — Reconciler Edge Cases
# ===================================================================


@pytest.mark.unit
class TestDeviceStateEvaluatorEdgeCases:
    async def test_spec_build_failed_skips_device(self) -> None:
        """Evaluator skips devices where build_recorder_spec raises."""
        device = MagicMock()
        device.name = "broken-mic"
        device.status = "online"
        device.enabled = True
        device.enrollment_status = "enrolled"
        device.profile_slug = "broken_profile"

        profile = MagicMock()
        profile.slug = "broken_profile"

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [device]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)
        session.get = AsyncMock(return_value=profile)

        evaluator = DeviceStateEvaluator()

        with patch(
            "silvasonic.controller.reconciler.build_recorder_spec",
            side_effect=ValueError("invalid config"),
        ):
            specs = await evaluator.evaluate(session)

        assert len(specs) == 0


@pytest.mark.unit
class TestReconciliationLoopEdgeCases:
    async def test_run_loop_handles_exception_and_continues(self) -> None:
        """run() catches exceptions in _reconcile_once and continues."""
        import asyncio

        mgr = MagicMock()
        loop = ReconciliationLoop(mgr, interval=0.01)

        call_count = 0

        async def failing_reconcile() -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError
            raise RuntimeError("DB unavailable")

        with (
            patch.object(loop, "_reconcile_once", side_effect=failing_reconcile),
            pytest.raises(asyncio.CancelledError),
        ):
            await loop.run()

        assert call_count >= 2

    async def test_trigger_wakes_run_loop(self) -> None:
        """trigger() wakes the run loop before the interval expires."""
        import asyncio

        mgr = MagicMock()
        loop = ReconciliationLoop(mgr, interval=999.0)  # Very long interval

        call_count = 0

        async def mock_reconcile() -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError

        with patch.object(loop, "_reconcile_once", side_effect=mock_reconcile):

            async def trigger_and_cancel() -> None:
                await asyncio.sleep(0.01)
                loop.trigger()

            task = asyncio.create_task(trigger_and_cancel())
            with pytest.raises(asyncio.CancelledError):
                await loop.run()
            await task

        assert call_count >= 2

    async def test_reconcile_once_calls_evaluate_and_reconcile(self) -> None:
        """_reconcile_once() queries DB, lists containers, and reconciles."""
        mgr = MagicMock()
        mgr.list_managed.return_value = [{"name": "existing"}]
        mock_spec = _make_spec()

        loop = ReconciliationLoop(mgr, interval=1.0)

        with (
            patch.object(
                loop._evaluator,
                "evaluate",
                new_callable=AsyncMock,
                return_value=[mock_spec],
            ),
            patch(
                "silvasonic.controller.reconciler.get_session",
            ) as mock_session,
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()

            await loop._reconcile_once()

        mgr.reconcile.assert_called_once()
        args = mgr.reconcile.call_args[0]
        assert args[0] == [mock_spec]
        assert args[1] == [{"name": "existing"}]
