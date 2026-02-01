from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.controller.hardware import AudioDevice
from silvasonic.controller.main import ControllerService
from silvasonic.core.database.models.system import Device


@pytest.fixture
def mock_scanner():
    """Mock the DeviceScanner."""
    with patch("silvasonic.controller.main.DeviceScanner") as mock:
        yield mock.return_value


@pytest.fixture
def mock_podman():
    """Mock the PodmanManager."""
    with patch("silvasonic.controller.main.PodmanManager") as mock:
        yield mock.return_value


@pytest.fixture
def mock_broker():
    """Mock the MessageBroker."""
    with patch("silvasonic.controller.main.MessageBroker") as mock:
        instance = mock.return_value
        instance.publish_heartbeat = AsyncMock()
        yield instance


@pytest.fixture
def service(mock_scanner, mock_podman, mock_broker):
    """Fixture for ControllerService with mocked dependencies."""
    return ControllerService()


@pytest.fixture
def mock_session_cls():
    """Fixture to mock AsyncSessionLocal context manager."""
    with patch("silvasonic.controller.main.AsyncSessionLocal") as mock:
        mock_session = AsyncMock()
        mock.return_value.__aenter__.return_value = mock_session
        yield mock_session


@pytest.mark.asyncio
async def test_reconcile_spawn_new_device(
    service, mock_scanner, mock_podman, mock_broker, mock_session_cls
):
    """Test that a new device is detected, added to DB, and started."""
    # Setup
    mock_podman.is_connected.return_value = True

    # Scanner finds a device
    dev = AudioDevice(card_index=1, id="UltraMic", description="Dodotronic", serial_number="SN123")
    mock_scanner.find_dodotronic_devices = MagicMock(return_value=[dev])

    # Podman has no active containers
    mock_podman.list_active_recorders.return_value = []
    mock_podman.spawn_recorder.return_value = True

    # Configure Session Mock via Fixture
    mock_session = mock_session_cls
    # Execute returns empty list (no existing devices) per call?
    # We need to configure the return value of execute()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result
    mock_session.add = MagicMock()

    # Run
    await service.reconcile()

    # Assertions
    # 2. DB: Should have added a new device
    assert mock_session.add.called
    # Verify added device has correct details
    args, _ = mock_session.add.call_args
    new_device = args[0]
    assert isinstance(new_device, Device)
    assert new_device.serial_number == "SN123"
    assert new_device.enabled is True

    # 3. Podman: Should spawn a container
    mock_podman.spawn_recorder.assert_called_once()
    call_kwargs = mock_podman.spawn_recorder.call_args.kwargs
    assert call_kwargs["serial_number"] == "SN123"
    assert call_kwargs["mic_name"] == new_device.name


@pytest.mark.asyncio
async def test_reconcile_stop_removed_device(
    service, mock_scanner, mock_podman, mock_broker, mock_session_cls
):
    """Test that a device missing from hardware is stopped."""
    # Setup
    mock_podman.is_connected.return_value = True

    # Scanner finds NO devices
    service.scanner.find_dodotronic_devices = MagicMock(return_value=[])

    # Podman has ONE active container
    mock_podman.list_active_recorders.return_value = [
        {"id": "cid-1", "name": "silvasonic-recorder-front", "device_serial": "SN123"}
    ]

    # Configure Session
    mock_session = mock_session_cls
    mock_session.add = MagicMock()
    existing_device = Device(name="mic_SN123", serial_number="SN123", enabled=True, status="online")
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [existing_device]
    mock_session.execute.return_value = mock_result

    # Run
    await service.reconcile()

    # Assertions
    # DB: Status set to offline?
    assert existing_device.status == "offline"

    # Podman: Stop called?
    mock_podman.stop_recorder.assert_called_with("cid-1")


@pytest.mark.asyncio
async def test_reconcile_exception_handling(service, mock_session_cls):
    """Test that reconcile handles exceptions gracefully."""
    # Setup to raise exception during podman check
    service.podman.is_connected.side_effect = Exception("Boom")

    # Run
    # Should catch exception and log it, not raise
    await service.reconcile()


@pytest.mark.asyncio
async def test_run_loop(service):
    """Test the main run loop."""
    # We mock reconcile to raise a special exception to break the infinite loop
    # or rely on side_effect iteration?

    service.reconcile = AsyncMock()

    # We want run() to call reconcile once then exit?
    # run() has 'while True'. We can mock asyncio.sleep to raise InterruptedError?

    with patch("asyncio.sleep", side_effect=InterruptedError):
        with pytest.raises(InterruptedError):
            await service.run()

    service.reconcile.assert_called_once()


@pytest.mark.asyncio
async def test_reconcile_podman_disconnected(service, mock_podman):
    """Test early return if podman is down."""
    mock_podman.is_connected.return_value = False

    await service.reconcile()

    mock_podman.list_active_recorders.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_scan_error(service, mock_scanner, mock_podman):
    """Test handling of hardware scan error."""
    mock_podman.is_connected.return_value = True
    # run_in_executor mock?
    # Since we mocked self.scanner.find..., and run_in_executor calls it.
    # If using standard asyncio loop, it will raise what the function raises?

    # Actually, we need to mock find_dodotronic_devices to raise
    mock_scanner.find_dodotronic_devices.side_effect = Exception("USB Error")

    await service.reconcile()

    # Should log error and return (empty detected_devices?)
    # In my code: catch Exception -> return.
    mock_podman.list_active_recorders.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_spawn_fail(
    service, mock_scanner, mock_podman, mock_broker, mock_session_cls
):
    """Test handling of spawn failure."""
    mock_podman.is_connected.return_value = True

    dev = AudioDevice(1, "Mic", "Desc", "SN1")
    mock_scanner.find_dodotronic_devices.return_value = [dev]
    mock_podman.list_active_recorders.return_value = []

    # Spawn fails
    mock_podman.spawn_recorder.return_value = False

    # Session
    mock_session = mock_session_cls
    mock_session.add = MagicMock()
    # Mock execute result for existing devices (none)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    await service.reconcile()

    mock_podman.spawn_recorder.assert_called_once()
    # Ensure no crash


@pytest.mark.asyncio
async def test_reconcile_stop_disabled(service, mock_scanner, mock_podman, mock_session_cls):
    """Test stopping a container if device is disabled in DB."""
    mock_podman.is_connected.return_value = True

    # Scanner finds device
    dev = AudioDevice(1, "Mic", "Desc", "SN1")
    mock_scanner.find_dodotronic_devices.return_value = [dev]

    # Podman: Container is running
    mock_podman.list_active_recorders.return_value = [
        {"id": "cid-1", "name": "rec-1", "device_serial": "SN1"}
    ]

    # DB: Device exists but DISABLED
    mock_session = mock_session_cls
    mock_session.add = MagicMock()

    db_dev = Device(name="mic_SN1", serial_number="SN1", enabled=False, status="online")

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [db_dev]
    mock_session.execute.return_value = mock_result

    await service.reconcile()

    mock_podman.stop_recorder.assert_called_with("cid-1")
