"""USB audio device scanner — detects microphones via ALSA + sysfs.

Enumerates ALSA cards from ``/proc/asound/cards``, correlates each with its
USB parent via ``sysfs``, and produces a :class:`DeviceInfo` for every
USB-audio device found.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# DeviceInfo — internal model (not a DB model)
# ---------------------------------------------------------------------------

_CARDS_PATH = Path("/proc/asound/cards")

# Regex to parse one entry from /proc/asound/cards, e.g.:
#  " 2 [UltraMic384K  ]: USB-Audio - UltraMic 384K"
_CARD_RE = re.compile(
    r"^\s*(?P<index>\d+)\s+\[(?P<id>[^\]]+)\]\s*:\s*(?P<driver>\S+)\s*-\s*(?P<name>.+)$",
)


class DeviceInfo(BaseModel):
    """Detected hardware device info (internal, not persisted as-is)."""

    alsa_card_index: int = Field(..., description="ALSA card index")
    alsa_name: str = Field(..., description="ALSA card name (e.g. 'UltraMic 384K')")
    alsa_device: str = Field(..., description="ALSA device string (e.g. 'hw:2,0')")

    usb_vendor_id: str | None = Field(default=None, description="USB Vendor ID (hex)")
    usb_product_id: str | None = Field(default=None, description="USB Product ID (hex)")
    usb_serial: str | None = Field(default=None, description="USB serial number")
    usb_bus_path: str | None = Field(default=None, description="USB bus path (e.g. '1-3.2')")

    @property
    def stable_device_id(self) -> str:
        """Compute a stable, unique device identifier.

        Priority:
        1. ``{vendor}-{product}-{serial}`` — globally unique
        2. ``{vendor}-{product}-port{bus_path}`` — port-bound
        3. ``alsa-card{index}`` — fallback (unstable across reboots)
        """
        if self.usb_vendor_id and self.usb_product_id and self.usb_serial:
            return f"{self.usb_vendor_id}-{self.usb_product_id}-{self.usb_serial}"
        if self.usb_vendor_id and self.usb_product_id and self.usb_bus_path:
            return f"{self.usb_vendor_id}-{self.usb_product_id}-port{self.usb_bus_path}"
        return f"alsa-card{self.alsa_card_index}"


class UsbInfo(BaseModel):
    """USB parent device info extracted from sysfs."""

    vendor_id: str | None = None
    product_id: str | None = None
    serial: str | None = None
    bus_path: str | None = None


# ---------------------------------------------------------------------------
# /proc/asound/cards parser
# ---------------------------------------------------------------------------


def parse_asound_cards(text: str) -> list[dict[str, str | int]]:
    """Parse ``/proc/asound/cards`` content into a list of card dicts.

    Returns:
        List of dicts with keys: ``index``, ``id``, ``driver``, ``name``.
    """
    cards: list[dict[str, str | int]] = []
    for line in text.splitlines():
        m = _CARD_RE.match(line)
        if m:
            cards.append(
                {
                    "index": int(m.group("index")),
                    "id": m.group("id").strip(),
                    "driver": m.group("driver"),
                    "name": m.group("name").strip(),
                }
            )
    return cards


# ---------------------------------------------------------------------------
# sysfs USB info extraction (pure pathlib)
# ---------------------------------------------------------------------------


def _read_sysfs(path: Path) -> str | None:
    """Read a sysfs attribute file, return stripped text or ``None``."""
    try:
        return path.read_text().strip() or None
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _get_usb_info_for_card(card_index: int) -> UsbInfo:
    """Look up USB parent info for an ALSA card via sysfs.

    Resolves the ``/sys/class/sound/cardN`` symlink and walks up the
    directory tree to find the USB parent device (``subsystem=usb``,
    ``DEVTYPE=usb_device``).

    Returns:
        :class:`UsbInfo` with populated fields if the card is a USB
        device, or all-``None`` defaults otherwise.
    """
    result = UsbInfo()

    card_path = Path(f"/sys/class/sound/card{card_index}")
    if not card_path.exists():
        return result

    try:
        # Resolve symlink to real sysfs device path
        real_path = card_path.resolve()

        # Walk up the directory tree to find the USB parent device
        current = real_path
        while current != current.parent:
            subsystem_link = current / "subsystem"
            if subsystem_link.is_symlink():
                subsystem_name = Path(os.readlink(subsystem_link)).name
                if subsystem_name == "usb":
                    # Check devtype via uevent file
                    uevent = _read_sysfs(current / "uevent")
                    if uevent and "DEVTYPE=usb_device" in uevent:
                        result.vendor_id = _read_sysfs(current / "idVendor")
                        result.product_id = _read_sysfs(current / "idProduct")
                        result.serial = _read_sysfs(current / "serial")
                        result.bus_path = current.name  # e.g. "1-3.2"
                        return result
            current = current.parent
    except Exception:
        log.exception("device_scanner.usb_lookup_failed", card_index=card_index)

    return result


# ---------------------------------------------------------------------------
# DeviceScanner
# ---------------------------------------------------------------------------


class DeviceScanner:
    """Scan for USB audio devices by reading ALSA cards and correlating with sysfs."""

    def __init__(self, cards_path: Path = _CARDS_PATH) -> None:
        """Initialize with path to ALSA cards file."""
        self._cards_path = cards_path

    def scan_all(self) -> list[DeviceInfo]:
        """Enumerate all USB-Audio devices currently connected.

        Reads ``/proc/asound/cards``, filters for USB-Audio drivers,
        and enriches each card with USB info from sysfs.

        Returns:
            List of :class:`DeviceInfo` for all USB-Audio cards found.
        """
        try:
            text = self._cards_path.read_text()
        except FileNotFoundError:
            log.warning("device_scanner.cards_not_found", path=str(self._cards_path))
            return []

        cards = parse_asound_cards(text)
        devices: list[DeviceInfo] = []

        for card in cards:
            driver = str(card["driver"])
            if driver != "USB-Audio":
                continue

            index = int(card["index"])
            usb = _get_usb_info_for_card(index)

            info = DeviceInfo(
                alsa_card_index=index,
                alsa_name=str(card["name"]),
                alsa_device=f"hw:{index},0",
                usb_vendor_id=usb.vendor_id,
                usb_product_id=usb.product_id,
                usb_serial=usb.serial,
                usb_bus_path=usb.bus_path,
            )
            devices.append(info)

        log.debug("device_scanner.scan_complete", devices_found=len(devices))
        return devices


# ---------------------------------------------------------------------------
# Backwards-compat re-export (moved to device_repository.py)
# ---------------------------------------------------------------------------
from silvasonic.controller.device_repository import (  # noqa: E402
    upsert_device as upsert_device,
)
