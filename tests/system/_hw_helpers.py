"""Shared hardware-detection helpers for system_hw tests.

Centralises USB-Audio detection, device scanning, and config-based
filtering that was previously duplicated across test_device_hotplug.py,
test_hw_recording.py, and test_zz_manual_hotplug.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from silvasonic.controller.device_scanner import DeviceInfo, DeviceScanner

if TYPE_CHECKING:
    from .conftest import HwMicConfig


def has_usb_audio_device() -> bool:
    """Check if any USB-Audio device is present in /proc/asound/cards."""
    try:
        text = Path("/proc/asound/cards").read_text()
        return "USB-Audio" in text
    except (FileNotFoundError, PermissionError):
        return False


def get_usb_devices() -> list[DeviceInfo]:
    """Scan for real USB audio devices using the actual sysfs."""
    scanner = DeviceScanner()
    return scanner.scan_all()


def find_by_config(devices: list[DeviceInfo], mic: HwMicConfig) -> list[DeviceInfo]:
    """Filter devices by USB VID/PID from a mic config."""
    return [d for d in devices if d.usb_vendor_id == mic.vid and d.usb_product_id == mic.pid]


def mic_connected(mic: HwMicConfig) -> bool:
    """Check if a specific mic (by VID/PID) is currently connected."""
    return len(find_by_config(get_usb_devices(), mic)) > 0
