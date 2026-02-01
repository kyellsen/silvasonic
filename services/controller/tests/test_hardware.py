import subprocess
from unittest.mock import mock_open, patch

import pytest
from silvasonic.controller.hardware import AudioDevice, DeviceScanner


@pytest.fixture
def scanner():
    """Fixture for DeviceScanner."""
    return DeviceScanner()


def test_device_scanner_properties(scanner):
    """Test display_name property of AudioDevice."""
    dev = AudioDevice(card_index=1, id="TestMic", description="Desc", serial_number="SN1")
    assert dev.display_name == "TestMic (Desc)"


def test_get_serial_success(scanner):
    """Test successful serial retrieval from primary path."""
    with patch("builtins.open", mock_open(read_data="SERIAL123\n")):
        serial = scanner._get_serial(1)
        assert serial == "SERIAL123"


def test_get_serial_fallback(scanner):
    """Test serial retrieval from fallback path (parent)."""
    # Mock open to raise FileNotFoundError on first call, return data on second
    # Side effect: First open fails, second succeeds
    # Note: mock_open doesn't support side_effect on 'open' calls easily for different paths without checking path.

    def side_effect(file, mode="r"):
        if "device/serial" in file:
            raise FileNotFoundError()
        if "device/../serial" in file:
            return mock_open(read_data="FALLBACK123").return_value
        raise FileNotFoundError()

    with patch("builtins.open", side_effect=side_effect):
        serial = scanner._get_serial(1)
        assert serial == "FALLBACK123"


def test_get_serial_none(scanner):
    """Test failure to retrieve serial."""
    with patch("builtins.open", side_effect=FileNotFoundError):
        serial = scanner._get_serial(1)
        assert serial is None


def test_scan_audio_devices_success(scanner):
    """Test parsing of arecord -l output."""
    output = "card 1: r0 [UltraMic384K_EVO 16bit r0], device 0: USB Audio [USB Audio]\n"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = output

        # Mock _get_serial to keep test focused (tested separately)
        with patch.object(scanner, "_get_serial", return_value="SN_MOCKED"):
            devices = scanner.scan_audio_devices()

            assert len(devices) == 1
            d = devices[0]
            assert d.card_index == 1
            assert d.id == "r0"
            assert d.description == "UltraMic384K_EVO 16bit r0"
            assert d.serial_number == "SN_MOCKED"
            assert d.device_index == 0


def test_scan_audio_devices_fallback_serial(scanner):
    """Test generation of fallback serial when sysfs fails."""
    output = "card 1: r0 [UltraMic384K_EVO 16bit r0], device 0: USB Audio [USB Audio]\n"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = output

        with patch.object(scanner, "_get_serial", return_value=None):
            devices = scanner.scan_audio_devices()
            assert len(devices) == 1
            # FORMAT: UNKNOWN-{id}-{card_index}
            assert devices[0].serial_number == "UNKNOWN-r0-1"


def test_scan_audio_devices_error(scanner):
    """Test subprocess error handling."""
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "cmd")):
        devices = scanner.scan_audio_devices()
        assert devices == []


def test_scan_audio_devices_not_found(scanner):
    """Test arecord missing handling."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        devices = scanner.scan_audio_devices()
        assert devices == []


def test_find_dodotronic_devices(scanner):
    """Test filtering logic."""
    dev1 = AudioDevice(1, "Ultramic", "Desc", "SN1")  # Match ID
    dev2 = AudioDevice(2, "Foo", "Dodotronic Mic", "SN2")  # Match Desc
    dev3 = AudioDevice(3, "Bar", "Generic Mic", "SN3")  # No Match

    with patch.object(scanner, "scan_audio_devices", return_value=[dev1, dev2, dev3]):
        matches = scanner.find_dodotronic_devices()
        assert len(matches) == 2
        assert dev1 in matches
        assert dev2 in matches
        assert dev3 not in matches
