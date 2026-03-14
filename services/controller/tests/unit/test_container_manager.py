"""Unit tests for Tier2ServiceSpec, build_recorder_spec, and ContainerManager.

Note: import json is used inside test_build_recorder_spec to verify CONFIG_JSON.

Covers spec validation, recorder spec factory, start/stop/remove/reconcile
operations, and edge cases (not connected, not found, connection errors).
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import (
    MountSpec,
    Tier2ServiceSpec,
    _container_name,
    _short_suffix,
    build_recorder_spec,
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
        assert parsed == {"audio": {"sample_rate": 384000, "channels": 1}}
        assert spec.labels["io.silvasonic.service"] == "recorder"
        # device_id label still uses stable_device_id (DB primary key)
        assert spec.labels["io.silvasonic.device_id"] == "0869-0389-00000000034F"
        assert spec.oom_score_adj == -999  # Protected
        assert spec.privileged is True
        assert len(spec.devices) == 1


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
class TestContainerName:
    """Tests for _container_name() — Podman-safe name generation."""

    def test_basic_name(self) -> None:
        """Builds correct name from slug + suffix."""
        assert _container_name("ultramic_384_evo", "034f") == (
            "silvasonic-recorder-ultramic-384-evo-034f"
        )

    def test_underscores_replaced(self) -> None:
        """Underscores in slug are replaced by hyphens."""
        assert _container_name("my_fancy_mic", "abcd") == ("silvasonic-recorder-my-fancy-mic-abcd")

    def test_already_lowercase(self) -> None:
        """Uppercase in slug is lowercased."""
        assert _container_name("UltraMic_EVO", "1234") == ("silvasonic-recorder-ultramic-evo-1234")


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
            {"name": "silvasonic-recorder-active", "status": "running"},
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

    def test_reconcile_empty_state(self) -> None:
        """reconcile() is a no-op when both desired and actual are empty."""
        client = MagicMock()
        client.is_connected = True
        mgr = ContainerManager(client)

        mgr.sync_state([], [])

        client.containers.run.assert_not_called()
        client.containers.get.assert_not_called()
