import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from podman.errors import APIError, NotFound
from silvasonic.controller.hardware import AudioDevice
from silvasonic.controller.orchestrator import PodmanOrchestrator


@pytest.fixture
def manager():
    """Fixture for PodmanOrchestrator with mocked client."""
    with patch("podman.PodmanClient") as mock_client:
        pm = PodmanOrchestrator()
        pm.client = mock_client.return_value  # Mock the client explicitly
        yield pm


def test_is_connected_true(manager):
    """Test is_connected success."""
    manager.client.ping.return_value = True
    assert manager.is_connected() is True


def test_is_connected_false(manager):
    """Test is_connected failure."""
    manager.client.ping.side_effect = Exception("Down")
    assert manager.is_connected() is False


def test_list_active_recorders_success(manager):
    """Test listing containers with mapping."""
    # Mock Container
    c1 = MagicMock()
    c1.id = "123"
    c1.name = "c1"
    c1.status = "running"
    c1.labels = {
        "device_serial": "SN1",
        "mic_name": "mic1",
        "service": "recorder",
        "managed_by": "silvasonic-controller",
    }

    manager.client.containers.list.return_value = [c1]

    res = manager.list_active_services()
    assert len(res) == 1
    assert res[0]["id"] == "123"
    assert res[0]["device_serial"] == "SN1"


def test_list_active_recorders_success_string_state(manager):
    """Test compatibility with Podman versions returning string State."""
    c2 = MagicMock()
    c2.id = "456"
    c2.name = "c2"
    # property access raises TypeError when State is a string
    type(c2).status = PropertyMock(side_effect=TypeError("string indices must be integers"))
    # The attribute causing the crash:
    c2.attrs = {"State": "running"}
    c2.labels = {
        "device_serial": "SN2",
        "service": "recorder",
        "managed_by": "silvasonic-controller",
    }

    manager.client.containers.list.return_value = [c2]

    res = manager.list_active_services()
    assert len(res) == 1
    assert res[0]["id"] == "456"
    assert res[0]["status"] == "running"


def test_list_active_recorders_error(manager):
    """Test listing containers API error."""
    manager.client.containers.list.side_effect = APIError("Err")
    res = manager.list_active_services()
    assert res == []


def test_spawn_recorder_success_new(manager):
    """Test spawning a new container."""
    # Not found -> Run
    manager.client.containers.get.side_effect = NotFound("Gone")

    dev = AudioDevice(1, "ID", "Desc", "SN1")
    config = {"slug": "prof"}
    config_hash = "hash123"

    success = manager.spawn_recorder(
        device=dev,
        mic_profile="prof",
        mic_name="mic1",
        serial_number="SN1",
        config=config,
        config_hash=config_hash,
    )

    assert success is True
    manager.client.containers.run.assert_called_once()
    kwargs = manager.client.containers.run.call_args.kwargs

    # Check Env Injection
    assert "MIC_CONFIG_JSON" in kwargs["environment"]
    assert kwargs["environment"]["MIC_CONFIG_JSON"] == json.dumps(config)

    # Check Hash Label
    assert kwargs["labels"]["silvasonic.config_hash"] == config_hash

    assert kwargs["image"] == "localhost/silvasonic-recorder"
    assert kwargs["name"] == "silvasonic-recorder-prof-sn1"
    # Verify mounts are used instead of volumes
    assert "mounts" in kwargs
    mounts = kwargs["mounts"]
    # We expect 3 mounts: data, profiles, logs
    assert len(mounts) == 3
    # Check that they are bind mounts
    assert all(m["Type"] == "bind" for m in mounts)

    # Verify one key mount target to be sure
    # Updated to expect friendly_name "prof-sn1" instead of "mic1"
    assert any(m["Target"] == "/data/recorder/prof-sn1" for m in mounts)

    # Verify security options (SELinux disabled)
    assert kwargs["security_opt"] == []

    # Verify Network
    assert kwargs["network"] == "silvasonic_silvasonic-net"


def test_spawn_recorder_already_running(manager):
    """Test skipping if already running."""
    c = MagicMock()
    c.status = "running"
    manager.client.containers.get.return_value = c

    dev = AudioDevice(1, "ID", "Desc", "SN1")
    # Provide defaults strictly for call signature matching
    success = manager.spawn_recorder(dev, "prof", "mic1", "SN1", {}, "hash")

    assert success is True
    manager.client.containers.run.assert_not_called()


def test_spawn_recorder_remove_stale(manager):
    """Test removing stale container before spawning."""
    c = MagicMock()
    c.status = "exited"
    manager.client.containers.get.return_value = c

    dev = AudioDevice(1, "ID", "Desc", "SN1")
    success = manager.spawn_recorder(dev, "prof", "mic1", "SN1", {}, "hash")

    assert success is True
    c.remove.assert_called_once()
    manager.client.containers.run.assert_called_once()


def test_spawn_recorder_error(manager):
    """Test handling spawn errors."""
    manager.client.containers.get.side_effect = Exception("Boom")

    dev = AudioDevice(1, "ID", "Desc", "SN1")
    success = manager.spawn_recorder(dev, "prof", "mic1", "SN1", {}, "hash")

    assert success is False


def test_stop_recorder_success(manager):
    """Test stopping a container."""
    c = MagicMock()
    manager.client.containers.get.return_value = c

    success = manager.stop_service("123")
    assert success is True
    c.stop.assert_called_once()
    c.remove.assert_called_once()


def test_stop_recorder_error(manager):
    """Test stopping error."""
    manager.client.containers.get.side_effect = Exception("Boom")
    success = manager.stop_service("123")
    assert success is False
