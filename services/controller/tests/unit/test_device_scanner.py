"""Unit tests for DeviceScanner — device detection and parsing.

All hardware (sysfs, /proc/asound) dependencies are mocked.
DB upsert tests are in test_device_repository.py.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from silvasonic.controller.device_scanner import (
    DeviceInfo,
    DeviceScanner,
    UsbInfo,
    _get_usb_info_for_card,
    _read_sysfs,
    parse_asound_cards,
)

# Fictional VID/PID for test isolation (not real hardware).
_MOCK_VID = "16d0"
_MOCK_PID = "0b40"


# ===========================================================================
# DeviceInfo — stable_device_id
# ===========================================================================
@pytest.mark.unit
class TestDeviceInfo:
    """Tests for the DeviceInfo model and stable_device_id property."""

    def test_stable_id_with_serial(self) -> None:
        """Full USB identity: vendor-product-serial."""
        info = DeviceInfo(
            alsa_card_index=2,
            alsa_name="UltraMic 384K",
            alsa_device="hw:2,0",
            usb_vendor_id=_MOCK_VID,
            usb_product_id=_MOCK_PID,
            usb_serial="ABC123",
            usb_bus_path="1-3.2",
        )
        assert info.stable_device_id == f"{_MOCK_VID}-{_MOCK_PID}-ABC123"

    def test_stable_id_without_serial(self) -> None:
        """No serial → port-bound fallback."""
        info = DeviceInfo(
            alsa_card_index=2,
            alsa_name="UltraMic 384K",
            alsa_device="hw:2,0",
            usb_vendor_id=_MOCK_VID,
            usb_product_id=_MOCK_PID,
            usb_serial=None,
            usb_bus_path="1-3.2",
        )
        assert info.stable_device_id == f"{_MOCK_VID}-{_MOCK_PID}-port1-3.2"

    def test_stable_id_fallback(self) -> None:
        """No USB info → ALSA card index fallback."""
        info = DeviceInfo(
            alsa_card_index=5,
            alsa_name="Some Card",
            alsa_device="hw:5,0",
        )
        assert info.stable_device_id == "alsa-card5"

    def test_stable_id_empty_strings(self) -> None:
        """Empty string vendor/product treated as missing → falls through to next level."""
        info = DeviceInfo(
            alsa_card_index=3,
            alsa_name="Card",
            alsa_device="hw:3,0",
            usb_vendor_id="",
            usb_product_id="",
        )
        # Empty strings are falsy → fallback to alsa-card
        assert info.stable_device_id == "alsa-card3"


# ===========================================================================
# parse_asound_cards
# ===========================================================================
@pytest.mark.unit
class TestParseAsoundCards:
    """Tests for /proc/asound/cards parser."""

    def test_parse_single_usb_card(self) -> None:
        """One USB-Audio card is parsed correctly."""
        text = " 2 [UltraMic384K  ]: USB-Audio - UltraMic 384K\n"
        cards = parse_asound_cards(text)
        assert len(cards) == 1
        assert cards[0]["index"] == 2
        assert cards[0]["id"] == "UltraMic384K"
        assert cards[0]["driver"] == "USB-Audio"
        assert cards[0]["name"] == "UltraMic 384K"

    def test_parse_multiple_cards(self) -> None:
        """Multiple cards, mixed drivers."""
        text = (
            " 0 [PCH             ]: HDA-Intel - HDA Intel PCH\n"
            "                      HDA Intel PCH at 0xf7200000 irq 32\n"
            " 1 [HDMI            ]: HDA-Intel - HDA Intel HDMI\n"
            "                      HDA Intel HDMI at 0xf7214000 irq 33\n"
            " 2 [UltraMic384K    ]: USB-Audio - UltraMic 384K\n"
            "                      Dodotronic UltraMic384K at usb-0000:00:14-2\n"
        )
        cards = parse_asound_cards(text)
        assert len(cards) == 3
        assert cards[0]["driver"] == "HDA-Intel"
        assert cards[2]["driver"] == "USB-Audio"

    def test_parse_empty_string(self) -> None:
        """Empty string returns empty list."""
        assert parse_asound_cards("") == []

    def test_parse_indented_description_lines_ignored(self) -> None:
        """Indented continuation lines are not matched."""
        text = (
            " 0 [PCH             ]: HDA-Intel - HDA Intel PCH\n"
            "                      HDA Intel PCH at 0xf7200000 irq 32\n"
        )
        cards = parse_asound_cards(text)
        assert len(cards) == 1


# ===========================================================================
# _read_sysfs
# ===========================================================================
@pytest.mark.unit
class TestReadSysfs:
    """Tests for the _read_sysfs helper function."""

    def test_read_existing_file(self, tmp_path: Any) -> None:
        """Returns stripped content from an existing file."""
        f = tmp_path / "idVendor"
        f.write_text("  16d0\n")
        assert _read_sysfs(f) == "16d0"

    def test_read_missing_file(self, tmp_path: Any) -> None:
        """Returns None when file does not exist."""
        assert _read_sysfs(tmp_path / "nonexistent") is None

    def test_read_empty_file(self, tmp_path: Any) -> None:
        """Returns None when file is empty (after strip)."""
        f = tmp_path / "serial"
        f.write_text("   \n")
        assert _read_sysfs(f) is None

    def test_read_permission_error(self, tmp_path: Any) -> None:
        """Returns None when file has no read permissions."""
        f = tmp_path / "protected"
        f.write_text("secret")
        f.chmod(0o000)
        try:
            assert _read_sysfs(f) is None
        finally:
            f.chmod(0o644)  # Restore for cleanup


# ===========================================================================
# _get_usb_info_for_card
# ===========================================================================
@pytest.mark.unit
class TestGetUsbInfoForCard:
    """Tests for _get_usb_info_for_card (sysfs USB parent lookup)."""

    def test_card_path_not_found(self) -> None:
        """Returns empty UsbInfo when /sys/class/sound/cardN does not exist."""
        with patch(
            "silvasonic.controller.device_scanner.Path",
        ) as mock_path_cls:
            mock_card_path = MagicMock()
            mock_card_path.exists.return_value = False
            mock_path_cls.return_value = mock_card_path

            result = _get_usb_info_for_card(99)

        assert result.vendor_id is None
        assert result.product_id is None

    def test_usb_parent_found(self, tmp_path: Any) -> None:
        """Returns populated UsbInfo when USB parent is found in sysfs tree."""
        # Build a fake sysfs tree:
        # tmp_path/1-3.2/sound/card2
        usb_parent = tmp_path / "1-3.2"
        card_dir = usb_parent / "sound" / "card2"
        card_dir.mkdir(parents=True)

        # USB parent has subsystem symlink → usb, uevent, and USB attrs
        subsystem_target = tmp_path / "bus" / "usb"
        subsystem_target.mkdir(parents=True)
        (usb_parent / "subsystem").symlink_to(subsystem_target)
        (usb_parent / "uevent").write_text("DEVTYPE=usb_device\nDRIVER=usb\n")
        (usb_parent / "idVendor").write_text("16d0\n")
        (usb_parent / "idProduct").write_text("0b40\n")
        (usb_parent / "serial").write_text("ABC123\n")

        with patch(
            "silvasonic.controller.device_scanner.Path",
        ) as mock_path_cls:
            # First call: Path(f"/sys/...") → redirect to our fake card_dir
            real_card_path = MagicMock()
            real_card_path.exists.return_value = True
            real_card_path.resolve.return_value = card_dir
            mock_path_cls.side_effect = lambda p: (
                real_card_path if "/sys/" in str(p) else type(card_dir)(p)
            )

            result = _get_usb_info_for_card(2)

        assert result.vendor_id == "16d0"
        assert result.product_id == "0b40"
        assert result.serial == "ABC123"
        assert result.bus_path == "1-3.2"

    def test_no_usb_subsystem(self, tmp_path: Any) -> None:
        """Returns empty UsbInfo when no USB subsystem is found."""
        # card_dir is at root of tmp_path — no USB parent above
        card_dir = tmp_path / "card0"
        card_dir.mkdir()

        with patch(
            "silvasonic.controller.device_scanner.Path",
        ) as mock_path_cls:
            real_card_path = MagicMock()
            real_card_path.exists.return_value = True
            real_card_path.resolve.return_value = card_dir
            mock_path_cls.return_value = real_card_path

            result = _get_usb_info_for_card(0)

        assert result.vendor_id is None

    def test_exception_returns_empty(self) -> None:
        """Returns empty UsbInfo on unexpected exceptions (logged)."""
        with (
            patch(
                "silvasonic.controller.device_scanner.Path",
            ) as mock_path_cls,
            patch("silvasonic.controller.device_scanner.log"),
        ):
            mock_card_path = MagicMock()
            mock_card_path.exists.return_value = True
            mock_card_path.resolve.side_effect = RuntimeError("unexpected")
            mock_path_cls.return_value = mock_card_path

            result = _get_usb_info_for_card(7)

        assert result.vendor_id is None
        assert result.product_id is None


# ===========================================================================
# DeviceScanner
# ===========================================================================
@pytest.mark.unit
class TestDeviceScanner:
    """Tests for the DeviceScanner class."""

    def test_scan_all_with_usb_card(self, tmp_path: Any) -> None:
        """scan_all returns DeviceInfo for USB-Audio cards."""
        cards_file = tmp_path / "cards"
        cards_file.write_text(
            " 0 [PCH             ]: HDA-Intel - HDA Intel PCH\n"
            " 2 [UltraMic384K    ]: USB-Audio - UltraMic 384K\n"
        )

        scanner = DeviceScanner(cards_path=cards_file)

        with patch(
            "silvasonic.controller.device_scanner._get_usb_info_for_card",
            return_value=UsbInfo(
                vendor_id=_MOCK_VID,
                product_id=_MOCK_PID,
                serial="ABC",
                bus_path="1-2",
            ),
        ):
            devices = scanner.scan_all()

        assert len(devices) == 1
        assert devices[0].alsa_name == "UltraMic 384K"
        assert devices[0].usb_vendor_id == _MOCK_VID
        assert devices[0].alsa_device == "hw:2,0"

    def test_scan_all_no_usb_cards(self, tmp_path: Any) -> None:
        """scan_all returns empty list when no USB-Audio cards exist."""
        cards_file = tmp_path / "cards"
        cards_file.write_text(" 0 [PCH             ]: HDA-Intel - HDA Intel PCH\n")
        scanner = DeviceScanner(cards_path=cards_file)
        devices = scanner.scan_all()
        assert devices == []

    def test_scan_all_file_not_found(self, tmp_path: Any) -> None:
        """scan_all returns empty list when /proc/asound/cards doesn't exist."""
        scanner = DeviceScanner(cards_path=tmp_path / "nonexistent")
        devices = scanner.scan_all()
        assert devices == []
