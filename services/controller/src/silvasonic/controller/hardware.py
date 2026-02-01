import re
import subprocess
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass(frozen=True)
class AudioDevice:
    """Represents a physical audio device detected on the host."""

    card_index: int
    id: str  # e.g. "Ultramic384E"
    description: str  # e.g. "UltraMic384K_EVO 16bit r0"
    serial_number: str  # e.g. "123456" or "UNKNOWN-..."
    device_index: int = 0

    @property
    def display_name(self) -> str:
        """Return a user-friendly display name."""
        return f"{self.id} ({self.description})"


class DeviceScanner:
    """Scans for audio devices using ALSA tools."""

    def _get_serial(self, card_index: int) -> str | None:
        """Try to read USB serial number from sysfs."""
        # /sys/class/sound/cardX/device refers to the usb interface
        # The serial is usually at /sys/class/sound/cardX/device/../../serial
        # But closer: /proc/asound/cardX/usbid exists?
        # Let's try /sys/class/sound/card{index}/device/serial (some drivers)
        # or list /sys/class/sound/card{index}/device/../serial

        # Safe fallback: None
        try:
            # Common location for USB audio devices
            serial_path = f"/sys/class/sound/card{card_index}/device/serial"
            with open(serial_path) as f:
                return f.read().strip()
        except FileNotFoundError:
            try:
                # Try parent (sometimes device links to interface, parent is device)
                # This is a bit rough without a robust traversing lib, but works for simple cases
                serial_path = f"/sys/class/sound/card{card_index}/device/../serial"
                with open(serial_path) as f:
                    return f.read().strip()
            except Exception:
                pass
        return None

    def scan_audio_devices(self) -> list[AudioDevice]:
        """List available ALSA input devices via 'arecord -l'."""
        try:
            # Capture output from arecord -l
            # Since we are in a container, we rely on the host's /dev/snd being mounted
            # and alsa-utils being installed in the container.
            # AND /sys must be mounted? usually is.
            res = subprocess.run(["arecord", "-l"], capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.error("arecord_failed", error=str(e))
            return []
        except FileNotFoundError:
            logger.error("arecord_not_found", hint="Is alsa-utils installed?")
            return []

        devices = []
        for line in res.stdout.splitlines():
            # Example Line:
            # card 1: r0 [UltraMic384K_EVO 16bit r0], device 0: USB Audio [USB Audio]

            # Regex to capture:
            # Group 1: Card Index
            # Group 2: ID (Short Name)
            # Group 3: Description (Long Name)
            # Group 4: Device Index
            m = re.search(r"card (\d+): (.*?) \[(.*?)\], device (\d+):", line)
            if m:
                idx = int(m.group(1))
                short_id = m.group(2).strip()
                # Try to get serial, otherwise use formatted ID as fallback unique-ish key
                serial = self._get_serial(idx) or f"UNKNOWN-{short_id}-{idx}"

                device = AudioDevice(
                    card_index=idx,
                    id=short_id,
                    description=m.group(3).strip(),
                    serial_number=serial,
                    device_index=int(m.group(4)),
                )
                devices.append(device)

        return devices

    def find_dodotronic_devices(self) -> list[AudioDevice]:
        """Filter for Dodotronic microphones."""
        all_devs = self.scan_audio_devices()
        return [
            d
            for d in all_devs
            if "dodotronic" in d.description.lower()
            or "ultramic" in d.id.lower()
            or "ultramic" in d.description.lower()
        ]
