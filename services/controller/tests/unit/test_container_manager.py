"""Unit tests for Tier2ServiceSpec, build_recorder_spec, and ContainerManager.

Note: import json is used inside test_build_recorder_spec to verify CONFIG_JSON.

Covers spec validation, recorder spec factory, start/stop/remove/reconcile
operations, and edge cases (not connected, not found, connection errors).
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import (
    MountSpec,
    Tier2ServiceSpec,
    _short_suffix,
    build_recorder_spec,
    generate_recorder_container_name,
    generate_workspace_name,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------
def _make_spec(**overrides: Any) -> Tier2ServiceSpec:
    """Create a minimal Tier2ServiceSpec for testing."""
    defaults: dict[str, Any] = {
        "image": "localhost/silvasonic_recorder:latest",
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
# Tier2ServiceSpec
# ===================================================================


@pytest.mark.unit
class TestTier2ServiceSpec:
    """Tests for the Tier2ServiceSpec Pydantic model."""

    def test_valid_spec(self) -> None:
        """Tier2ServiceSpec validates with all required fields."""
        spec = _make_spec()
        assert spec.image == "localhost/silvasonic_recorder:latest"
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


# ===================================================================
# build_recorder_spec
# ===================================================================


@pytest.mark.unit
class TestBuildRecorderSpec:
    """Tests for the build_recorder_spec factory function."""

    def test_build_recorder_spec(self) -> None:
        """build_recorder_spec creates a valid spec from Device + Profile."""
        import json

        device = MagicMock()
        device.name = "0869-0389-00000000034F"
        device.config = {
            "alsa_device": "hw:2,0",
            "usb_serial": "00000000034F",
        }

        profile = MagicMock()
        profile.slug = "ultramic_384_evo"
        profile.config = {"audio": {"sample_rate": 384000, "channels": 1}}

        spec = build_recorder_spec(device, profile)

        # Human-readable name: slug + last 4 hex of serial
        assert spec.name == "silvasonic-recorder-ultramic-384-evo-034f"
        assert spec.image == "localhost/silvasonic_recorder:latest"
        assert spec.environment["SILVASONIC_RECORDER_DEVICE"] == "hw:2,0"
        assert spec.environment["SILVASONIC_RECORDER_PROFILE_SLUG"] == "ultramic_384_evo"
        # CONFIG_JSON contains the full profile config (ADR-0016, Option C)
        assert "SILVASONIC_RECORDER_CONFIG_JSON" in spec.environment
        parsed = json.loads(spec.environment["SILVASONIC_RECORDER_CONFIG_JSON"])
        assert parsed["audio"]["sample_rate"] == 384000
        assert parsed["audio"]["channels"] == 1
        assert parsed["audio"]["format"] == "S16LE"
        assert "processing" in parsed
        assert "stream" in parsed
        assert spec.labels["io.silvasonic.service"] == "recorder"
        # device_id label still uses stable_device_id (DB primary key)
        assert spec.labels["io.silvasonic.device_id"] == "0869-0389-00000000034F"
        assert spec.oom_score_adj == -999  # Protected
        assert spec.privileged is True
        assert len(spec.devices) == 1

    def test_recorder_spec_suppresses_pulse_and_pipewire(self) -> None:
        """Recorder spec sets PULSE_SERVER='' and PIPEWIRE_RUNTIME_DIR='' to force ALSA."""
        device = MagicMock()
        device.name = "test-device"
        device.config = {"alsa_device": "hw:1,0", "usb_serial": "1234"}

        profile = MagicMock()
        profile.slug = "test_mic"
        profile.config = {"audio": {"sample_rate": 48000}}

        spec = build_recorder_spec(device, profile)

        assert spec.environment["PULSE_SERVER"] == ""
        assert spec.environment["PIPEWIRE_RUNTIME_DIR"] == ""


@pytest.mark.unit
class TestShortSuffix:
    """Tests for _short_suffix() — device identity suffix generation."""

    def test_serial_suffix(self) -> None:
        """Uses last 4 hex chars of USB serial."""
        device = MagicMock()
        device.config = {"usb_serial": "00000000034F"}
        assert _short_suffix(device) == "034f"

    def test_serial_uppercase_to_lower(self) -> None:
        """Serial suffix is always lowercase."""
        device = MagicMock()
        device.config = {"usb_serial": "AABB1234CDEF"}
        assert _short_suffix(device) == "cdef"

    def test_bus_path_suffix(self) -> None:
        """Falls back to USB bus path when no serial."""
        device = MagicMock()
        device.config = {"usb_serial": None, "usb_bus_path": "1-3.2"}
        assert _short_suffix(device) == "p1d3"

    def test_bus_path_no_serial_key(self) -> None:
        """Works when serial key is missing entirely."""
        device = MagicMock()
        device.config = {"usb_bus_path": "2-1"}
        assert _short_suffix(device) == "p2d1"

    def test_card_index_fallback(self) -> None:
        """Falls back to ALSA card index when no USB info."""
        device = MagicMock()
        device.config = {"alsa_card_index": 3}
        assert _short_suffix(device) == "c003"

    def test_empty_config_fallback(self) -> None:
        """Returns c000 when config is empty."""
        device = MagicMock()
        device.config = {}
        assert _short_suffix(device) == "c000"


@pytest.mark.unit
class TestGenerateRecorderContainerName:
    """Tests for generate_recorder_container_name() — standard Podman name generation."""

    def test_basic_name(self) -> None:
        """Builds correct container name by prepending standard prefix."""
        assert generate_recorder_container_name("ultramic-384-evo-034f") == (
            "silvasonic-recorder-ultramic-384-evo-034f"
        )


# ===================================================================
# ContainerManager
# ===================================================================


@pytest.mark.unit
class TestContainerManager:
    """Tests for the ContainerManager class."""

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
        # Verify networks dict is correctly passed (named network)
        call_kwargs = client.containers.run.call_args.kwargs
        assert call_kwargs["network_mode"] == "bridge"
        assert call_kwargs["networks"] == {"silvasonic-net": {}}

    def test_start_skips_running(self) -> None:
        """start() returns existing container info if already running."""
        existing = MagicMock()
        existing.id = "abc123"
        existing.name = "silvasonic-recorder-test"
        existing.attrs = {"State": "running"}
        existing.labels = {}

        client = MagicMock()
        client.is_connected = True
        client.containers.get.return_value = existing

        mgr = ContainerManager(client)
        result = mgr.start(_make_spec())

        assert result is not None
        assert result["status"] == "running"
        client.containers.run.assert_not_called()

    def test_start_replaces_exited_container(self) -> None:
        """start() removes an exited container and recreates it using stateful Fake."""
        from podman.errors import NotFound

        # A stateful mock to simulate Podman's state transitions correctly
        class FakeContainers:
            def __init__(self) -> None:
                self.mock_container = MagicMock()
                self.mock_container.id = "dead123"
                self.mock_container.name = "silvasonic-recorder-test"
                self.mock_container.status = "exited"
                self.mock_container.attrs = {"State": "exited"}
                self.removed = False
                self.removed_force = False
                self.run_count = 0

                def _stop(*args: Any, **kwargs: Any) -> None:
                    self.mock_container.status = "exited"
                    self.mock_container.attrs["State"] = "exited"

                def _remove(force: bool = False) -> None:
                    self.removed = True
                    self.removed_force = force

                self.mock_container.stop.side_effect = _stop
                self.mock_container.remove.side_effect = _remove

            def get(self, name: str) -> Any:
                if self.removed:
                    raise NotFound(f"Container {name} not found")
                return self.mock_container

            def run(self, **kwargs: Any) -> Any:
                self.run_count += 1
                new_container = MagicMock()
                new_container.id = "new456"
                new_container.name = kwargs.get("name")
                new_container.status = "running"
                new_container.attrs = {"State": "running"}
                new_container.labels = {}
                return new_container

        fake = FakeContainers()
        client = MagicMock()
        client.is_connected = True
        client.containers = fake

        mgr = ContainerManager(client)
        result = mgr.start(_make_spec())

        assert result is not None
        assert result["status"] == "running"
        assert fake.removed is True
        assert fake.removed_force is True
        assert fake.run_count == 1
        fake.mock_container.stop.assert_called_once()
        fake.mock_container.remove.assert_called_once_with(force=True)

    def test_start_exception_returns_none(self) -> None:
        """start() returns None on unexpected exceptions."""
        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = Exception("not found")
        client.containers.run.side_effect = RuntimeError("image not found")
        mgr = ContainerManager(client)

        result = mgr.start(_make_spec())
        assert result is None

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

    def test_stop_not_found_returns_true(self) -> None:
        """stop() returns True when container is already gone (NotFound)."""
        from podman.errors import NotFound

        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = NotFound("gone")
        mgr = ContainerManager(client)

        result = mgr.stop("vanished-container")
        assert result is True

    def test_stop_connection_error_returns_false(self) -> None:
        """stop() returns False on ConnectionError."""
        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = ConnectionError("socket gone")
        mgr = ContainerManager(client)

        assert mgr.stop("unreachable-container") is False

    def test_stop_json_decode_error_returns_true(self) -> None:
        """stop() returns True on JSONDecodeError (race: container already exited)."""
        import json

        client = MagicMock()
        client.is_connected = True
        client.containers.get.return_value.stop.side_effect = json.JSONDecodeError(
            "Expecting value", "", 0
        )
        mgr = ContainerManager(client)

        assert mgr.stop("race-container") is True

    def test_stop_api_error_returns_true(self) -> None:
        """stop() returns True on APIError (race: container stop conflict)."""
        from podman.errors import APIError

        client = MagicMock()
        client.is_connected = True
        client.containers.get.return_value.stop.side_effect = APIError("container already stopped")
        mgr = ContainerManager(client)

        assert mgr.stop("stopped-container") is True

    def test_remove_force_removes(self) -> None:
        """remove() force-removes a container."""
        client = MagicMock()
        client.is_connected = True
        mgr = ContainerManager(client)

        result = mgr.remove("test-container")
        assert result is True

    def test_remove_not_connected_returns_false(self) -> None:
        """remove() returns False when Podman is not connected."""
        client = MagicMock()
        client.is_connected = False
        mgr = ContainerManager(client)

        assert mgr.remove("test-container") is False

    def test_remove_not_found_returns_true(self) -> None:
        """remove() returns True when container is already gone (NotFound)."""
        from podman.errors import NotFound

        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = NotFound("gone")
        mgr = ContainerManager(client)

        result = mgr.remove("vanished-container")
        assert result is True

    def test_remove_unexpected_error_returns_false(self) -> None:
        """remove() returns False on unexpected exceptions."""
        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = ConnectionError("socket gone")
        mgr = ContainerManager(client)

        assert mgr.remove("test-container") is False

    def test_remove_api_error_retries_and_succeeds(self) -> None:
        """remove() retries on APIError and succeeds on second attempt."""
        from podman.errors import APIError

        first_container = MagicMock()
        first_container.remove.side_effect = APIError("container is stopping")
        second_container = MagicMock()

        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = [first_container, second_container]
        mgr = ContainerManager(client)

        with patch("time.sleep"):
            result = mgr.remove("stopping-container")

        assert result is True
        second_container.remove.assert_called_once_with(force=True)

    def test_remove_api_error_retry_not_found(self) -> None:
        """remove() returns True when container disappears during retry."""
        from podman.errors import APIError, NotFound

        first_container = MagicMock()
        first_container.remove.side_effect = APIError("container is stopping")

        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = [first_container, NotFound("gone")]
        mgr = ContainerManager(client)

        with patch("time.sleep"):
            result = mgr.remove("vanishing-container")

        assert result is True

    def test_remove_api_error_retry_fails(self) -> None:
        """remove() returns False when retry also fails."""
        from podman.errors import APIError

        first_container = MagicMock()
        first_container.remove.side_effect = APIError("container is stopping")
        second_container = MagicMock()
        second_container.remove.side_effect = APIError("still stopping")

        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = [first_container, second_container]
        mgr = ContainerManager(client)

        with patch("time.sleep"):
            result = mgr.remove("stuck-container")

        assert result is False

    def test_stop_and_remove_calls_both(self) -> None:
        """stop_and_remove() delegates to stop() then remove()."""
        client = MagicMock()
        client.is_connected = True
        mgr = ContainerManager(client)

        result = mgr.stop_and_remove("test-container", timeout=5)

        assert result is True
        container = client.containers.get.return_value
        container.stop.assert_called_once_with(timeout=5)
        container.remove.assert_called_once_with(force=True)

    def test_stop_and_remove_not_connected(self) -> None:
        """stop_and_remove() returns False when not connected."""
        client = MagicMock()
        client.is_connected = False
        mgr = ContainerManager(client)

        assert mgr.stop_and_remove("unreachable") is False

    def test_build_run_kwargs_structure(self) -> None:
        """_build_run_kwargs() builds correct kwargs dict from spec."""
        spec = _make_spec(name="silvasonic-recorder-test")
        kwargs = ContainerManager._build_run_kwargs(spec)

        assert kwargs["image"] == spec.image
        assert kwargs["name"] == spec.name
        assert kwargs["detach"] is True
        assert kwargs["network_mode"] == "bridge"
        assert kwargs["networks"] == {spec.network: {}}
        assert kwargs["mem_limit"] == spec.memory_limit
        assert kwargs["oom_score_adj"] == spec.oom_score_adj
        assert kwargs["cpu_quota"] == int(spec.cpu_limit * 100_000)
        assert isinstance(kwargs["restart_policy"], dict)
        assert kwargs["restart_policy"]["Name"] == "on-failure"

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

    def test_get_not_connected_returns_none(self) -> None:
        """get() returns None when Podman is not connected."""
        client = MagicMock()
        client.is_connected = False
        mgr = ContainerManager(client)

        assert mgr.get("test") is None

    def test_list_managed_delegates(self) -> None:
        """list_managed() delegates to podman_client.list_managed_containers()."""
        client = MagicMock()
        client.list_managed_containers.return_value = [{"name": "test"}]
        mgr = ContainerManager(client)

        result = mgr.list_managed()
        assert result == [{"name": "test"}]
        client.list_managed_containers.assert_called_once()

    def test_reconcile_starts_missing_and_stops_orphaned(self) -> None:
        """reconcile() starts missing containers, stops+removes orphaned."""
        from podman.errors import NotFound

        mock_container = MagicMock()
        mock_container.id = "new123"
        mock_container.name = "silvasonic-recorder-new"
        mock_container.status = "running"
        mock_container.labels = {}

        # get() must return NotFound for the "new" spec (so start creates it)
        # but succeed for "orphan" (so stop and remove work)
        orphan_container = MagicMock()

        def get_side_effect(name: str) -> Any:
            if name == "silvasonic-recorder-new":
                raise NotFound("not found")
            return orphan_container

        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = get_side_effect
        client.containers.run.return_value = mock_container

        mgr = ContainerManager(client)

        desired = [_make_spec(name="silvasonic-recorder-new")]
        actual: list[dict[str, object]] = [
            {"name": "silvasonic-recorder-orphan", "status": "running"},
        ]

        mgr.sync_state(desired, actual)

        # Should start "new"
        client.containers.run.assert_called_once()
        # Should stop+remove "orphan"
        orphan_container.stop.assert_called_once()
        orphan_container.remove.assert_called_once()

    def test_reconcile_adopts_running(self) -> None:
        """reconcile() adopts containers that are desired AND already running."""
        client = MagicMock()
        client.is_connected = True
        mgr = ContainerManager(client)

        spec = _make_spec(name="silvasonic-recorder-active")
        desired = [spec]
        actual: list[dict[str, object]] = [
            {
                "name": "silvasonic-recorder-active",
                "status": "running",
                "labels": {"io.silvasonic.config_hash": spec.config_hash},
            },
        ]

        mgr.sync_state(desired, actual)

        # Should NOT start or stop anything
        client.containers.run.assert_not_called()
        client.containers.get.assert_not_called()

    def test_reconcile_only_orphaned(self) -> None:
        """reconcile() stops+removes all orphans when nothing is desired."""
        orphan_container = MagicMock()

        client = MagicMock()
        client.is_connected = True
        client.containers.get.return_value = orphan_container
        mgr = ContainerManager(client)

        desired: list[Tier2ServiceSpec] = []
        actual: list[dict[str, object]] = [
            {"name": "silvasonic-recorder-old", "status": "running"},
        ]

        mgr.sync_state(desired, actual)

        # Should stop+remove the orphan, should NOT start anything
        orphan_container.stop.assert_called_once()
        orphan_container.remove.assert_called_once()
        client.containers.run.assert_not_called()

    def test_reconcile_only_missing(self) -> None:
        """reconcile() starts all missing when nothing is running."""
        from podman.errors import NotFound

        mock_container = MagicMock()
        mock_container.id = "new123"
        mock_container.name = "silvasonic-recorder-new"
        mock_container.status = "running"
        mock_container.labels = {}

        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = NotFound("not found")
        client.containers.run.return_value = mock_container
        mgr = ContainerManager(client)

        desired = [_make_spec(name="silvasonic-recorder-new")]
        actual: list[dict[str, object]] = []

        mgr.sync_state(desired, actual)

        # Should start "new", nothing to stop
        client.containers.run.assert_called_once()

    def test_reconcile_restarts_on_config_drift(self) -> None:
        """reconcile() stops and restarts container passing identical name but mismatched config."""
        from podman.errors import NotFound

        mock_container = MagicMock()
        mock_container.id = "drift123"
        mock_container.name = "silvasonic-recorder-drift"
        mock_container.status = "running"
        mock_container.labels = {"io.silvasonic.config_hash": "old_hash_123"}

        client = MagicMock()
        client.is_connected = True

        # Simulate NotFound after removal to prevent start() from trying to stop it again
        def mock_get(name: str) -> MagicMock:
            if mock_container.remove.called:
                raise NotFound("already removed")
            return mock_container

        client.containers.get.side_effect = mock_get
        client.containers.run.return_value = mock_container
        mgr = ContainerManager(client)

        from unittest.mock import PropertyMock, patch

        spec = _make_spec(
            name="silvasonic-recorder-drift",
            labels={"io.silvasonic.config_hash": "new_hash_456"},
        )

        desired = [spec]
        actual: list[dict[str, object]] = [
            {
                "name": "silvasonic-recorder-drift",
                "status": "running",
                "labels": {"io.silvasonic.config_hash": "old_hash_123"},
            }
        ]

        with patch(
            "silvasonic.controller.container_spec.Tier2ServiceSpec.config_hash",
            new_callable=PropertyMock,
        ) as mock_hash:
            mock_hash.return_value = "new_hash_456"
            mgr.sync_state(desired, actual)

        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()
        client.containers.run.assert_called_once()

    def test_reconcile_empty_state(self) -> None:
        """reconcile() is a no-op when both desired and actual are empty."""
        client = MagicMock()
        client.is_connected = True
        mgr = ContainerManager(client)

        mgr.sync_state([], [])

        client.containers.run.assert_not_called()
        client.containers.get.assert_not_called()

    def test_start_passes_devices_and_group_add(self) -> None:
        """start() passes devices and group_add to containers.run when non-empty."""
        from podman.errors import NotFound

        mock_container = MagicMock()
        mock_container.id = "dev123"
        mock_container.name = "silvasonic-recorder-test"
        mock_container.status = "running"
        mock_container.labels = {}

        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = NotFound("not found")
        client.containers.run.return_value = mock_container
        mgr = ContainerManager(client)

        spec = _make_spec(
            devices=["/dev/snd/pcmC2D0c"],
            group_add=["audio"],
        )
        mgr.start(spec)

        call_kwargs = client.containers.run.call_args.kwargs
        assert call_kwargs["devices"] == ["/dev/snd/pcmC2D0c"]
        assert call_kwargs["group_add"] == ["audio"]

    def test_start_creates_bind_mount_dirs(self, tmp_path: "Any") -> None:
        """start() creates bind-mount source directories that don't exist."""
        from podman.errors import NotFound

        mock_container = MagicMock()
        mock_container.id = "dir123"
        mock_container.name = "silvasonic-recorder-test"
        mock_container.status = "running"
        mock_container.labels = {}

        client = MagicMock()
        client.is_connected = True
        client.containers.get.side_effect = NotFound("not found")
        client.containers.run.return_value = mock_container
        mgr = ContainerManager(client)

        mount_dir = tmp_path / "workspace" / "recorder" / "audio"
        spec = _make_spec(
            mounts=[
                MountSpec(
                    source=str(mount_dir),
                    target="/workspace/recorder/audio",
                    read_only=False,
                    controller_source=str(mount_dir),
                ),
            ],
        )
        mgr.start(spec)

        assert mount_dir.exists()


# ===================================================================
# Workspace-to-Device Name Contract (Bug #1: Name-Mismatch)
# ===================================================================


@pytest.mark.unit
class TestWorkspaceNameContract:
    """Verify generate_workspace_name contract with build_recorder_spec.

    The function must produce a consistent name that can be stored in
    ``devices.workspace_name`` and matches the workspace directory
    derived from ``build_recorder_spec``.

    The Processor Indexer extracts workspace_dir from the filesystem and
    queries ``SELECT name FROM devices WHERE workspace_name = :ws_name``.
    The ``workspace_name`` column is set by the Controller during enrollment.

    See: Log Analysis Report 2026-03-30 — Bug #1 (Name-Mismatch).
    """

    def test_workspace_name_matches_container_dir_serial(self) -> None:
        """generate_workspace_name matches build_recorder_spec workspace dir.

        Production scenario: Ultramic 384K EVO with USB serial.
        - device.name (stable_device_id) = "0869-0389-00000000034F"
        - workspace_name = "ultramic-384-evo-034f" (stored in DB)
        - container_name = "silvasonic-recorder-ultramic-384-evo-034f"
        """
        device = MagicMock()
        device.name = "0869-0389-00000000034F"
        device.config = {
            "alsa_device": "hw:2,0",
            "usb_serial": "00000000034F",
            "usb_vendor_id": "0869",
            "usb_product_id": "0389",
        }

        profile = MagicMock()
        profile.slug = "ultramic_384_evo"
        profile.config = {"audio": {"sample_rate": 384000, "channels": 1}}

        ws = generate_workspace_name(profile.slug, device)
        spec = build_recorder_spec(device, profile)
        workspace_dir = spec.name.removeprefix("silvasonic-recorder-")

        assert ws == workspace_dir, (
            f"Contract violation: generate_workspace_name='{ws}' "
            f"differs from spec workspace_dir='{workspace_dir}'."
        )
        assert ws == "ultramic-384-evo-034f"

    def test_workspace_name_matches_container_dir_bus_path(self) -> None:
        """generate_workspace_name matches build_recorder_spec workspace dir.

        Production scenario: Rode NT-USB without serial (uses bus path).
        - device.name (stable_device_id) = "19f7-0003-port3-6"
        - workspace_name = "rode-nt-usb-p3d6" (stored in DB)
        """
        device = MagicMock()
        device.name = "19f7-0003-port3-6"
        device.config = {
            "alsa_device": "hw:1,0",
            "usb_vendor_id": "19f7",
            "usb_product_id": "0003",
            "usb_bus_path": "3-6",
        }

        profile = MagicMock()
        profile.slug = "rode_nt_usb"
        profile.config = {"audio": {"sample_rate": 48000, "channels": 2}}

        ws = generate_workspace_name(profile.slug, device)
        spec = build_recorder_spec(device, profile)
        workspace_dir = spec.name.removeprefix("silvasonic-recorder-")

        assert ws == workspace_dir, (
            f"Contract violation: generate_workspace_name='{ws}' "
            f"differs from spec workspace_dir='{workspace_dir}'."
        )
        assert ws == "rode-nt-usb-p3d6"
