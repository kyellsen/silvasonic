from unittest.mock import MagicMock, patch

import pytest
from podman.errors import APIError, NotFound
from silvasonic.controller.hardware import AudioDevice
from silvasonic.controller.orchestrator import PodmanManager


@pytest.fixture
def manager():
    """Fixture for PodmanManager with mocked client."""
    with patch("podman.PodmanClient") as mock_client:
        pm = PodmanManager()
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
    c1.labels = {"device_serial": "SN1", "mic_name": "mic1"}

    manager.client.containers.list.return_value = [c1]

    res = manager.list_active_recorders()
    assert len(res) == 1
    assert res[0]["id"] == "123"
    assert res[0]["device_serial"] == "SN1"


def test_list_active_recorders_error(manager):
    """Test listing containers API error."""
    manager.client.containers.list.side_effect = APIError("Err")
    res = manager.list_active_recorders()
    assert res == []


def test_spawn_recorder_success_new(manager):
    """Test spawning a new container."""
    # Not found -> Run
    manager.client.containers.get.side_effect = NotFound("Gone")

    dev = AudioDevice(1, "ID", "Desc", "SN1")
    success = manager.spawn_recorder(dev, "prof", "mic1", "SN1")

    assert success is True
    manager.client.containers.run.assert_called_once()
    kwargs = manager.client.containers.run.call_args.kwargs
    assert kwargs["image"] == "silvasonic-recorder"
    assert kwargs["name"] == "silvasonic-recorder-mic1"
    # Verify volumes include :z
    assert any(":z" in v for v in kwargs["volumes"])


def test_spawn_recorder_already_running(manager):
    """Test skipping if already running."""
    c = MagicMock()
    c.status = "running"
    manager.client.containers.get.return_value = c

    dev = AudioDevice(1, "ID", "Desc", "SN1")
    success = manager.spawn_recorder(dev, "prof", "mic1", "SN1")

    assert success is True
    manager.client.containers.run.assert_not_called()


def test_spawn_recorder_remove_stale(manager):
    """Test removing stale container before spawning."""
    c = MagicMock()
    c.status = "exited"
    manager.client.containers.get.return_value = c

    dev = AudioDevice(1, "ID", "Desc", "SN1")
    success = manager.spawn_recorder(dev, "prof", "mic1", "SN1")

    assert success is True
    c.remove.assert_called_once()
    manager.client.containers.run.assert_called_once()


def test_spawn_recorder_error(manager):
    """Test handling spawn errors."""
    manager.client.containers.get.side_effect = Exception("Boom")

    dev = AudioDevice(1, "ID", "Desc", "SN1")
    success = manager.spawn_recorder(dev, "prof", "mic1", "SN1")

    assert success is False


def test_stop_recorder_success(manager):
    """Test stopping a container."""
    c = MagicMock()
    manager.client.containers.get.return_value = c

    success = manager.stop_recorder("123")
    assert success is True
    c.stop.assert_called_once()
    c.remove.assert_called_once()


def test_stop_recorder_error(manager):
    """Test stopping error."""
    manager.client.containers.get.side_effect = Exception("Boom")
    success = manager.stop_recorder("123")
    assert success is False
