"""Interactive hot-plug tests — require physical unplug/re-plug actions.

These tests call ``input()`` and therefore MUST run last in the
``just test-hw`` pipeline.  They are separated from the automated tests
in ``test_device_hotplug.py`` so that all non-interactive tests finish
first — the developer only needs to be at the keyboard when these run.

File sorts alphabetically **after** ``test_hw_recording.py`` by design
(``zz_`` prefix).

All tests require ``-s`` flag (stdin capture disabled) for ``input()`` prompts.

Skip conditions:
- Primary mic not connected → single-mic tests skipped
- Both mics not connected → dual-mic tests skipped
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from silvasonic.controller.device_scanner import DeviceInfo, DeviceScanner, upsert_device
from silvasonic.controller.profile_matcher import ProfileMatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import (
    PRIMARY_MIC,
    SECONDARY_MIC,
    HwMicConfig,
)

pytestmark = [
    pytest.mark.system_hw,
]


# ---------------------------------------------------------------------------
# Hardware detection helpers (shared with test_device_hotplug.py)
# ---------------------------------------------------------------------------


def _has_usb_audio_device() -> bool:
    """Check if any USB-Audio device is present in /proc/asound/cards."""
    try:
        text = Path("/proc/asound/cards").read_text()
        return "USB-Audio" in text
    except (FileNotFoundError, PermissionError):
        return False


def _get_usb_devices() -> list[DeviceInfo]:
    """Scan for real USB audio devices using the actual sysfs."""
    scanner = DeviceScanner()
    return scanner.scan_all()


def _find_by_config(devices: list[DeviceInfo], mic: HwMicConfig) -> list[DeviceInfo]:
    """Filter devices by USB VID/PID from a mic config."""
    return [d for d in devices if d.usb_vendor_id == mic.vid and d.usb_product_id == mic.pid]


def _mic_connected(mic: HwMicConfig) -> bool:
    """Check if a specific mic (by VID/PID) is currently connected."""
    return len(_find_by_config(_get_usb_devices(), mic)) > 0


_USB_PRESENT = _has_usb_audio_device()
_PRIMARY_CONNECTED = _USB_PRESENT and _mic_connected(PRIMARY_MIC)
_SECONDARY_CONNECTED = _USB_PRESENT and SECONDARY_MIC is not None and _mic_connected(SECONDARY_MIC)
_BOTH_CONNECTED = _PRIMARY_CONNECTED and _SECONDARY_CONNECTED


# ---------------------------------------------------------------------------
# Terminal output helpers
# ---------------------------------------------------------------------------

_SETTLE_UNPLUG_S = 2
_SETTLE_REPLUG_S = 3
_W = 60  # box width

# Global step counter for interactive prompts.
_action_step = 0
_action_total = 0


def _init_action_counter() -> None:
    """Calculate total expected interactive prompts for the session."""
    global _action_total
    total = 0
    if _BOTH_CONNECTED:
        total += 4  # dual-mic suite only
    else:
        if _PRIMARY_CONNECTED:
            total += 2  # single primary
        if _SECONDARY_CONNECTED:
            total += 2  # single secondary
    _action_total = total


_init_action_counter()


def _settle_wait(seconds: int, label: str = "Settling") -> None:
    """Show a live countdown during udev/ALSA settle time."""
    for remaining in range(seconds, 0, -1):
        sys.stdout.write(f"\r  ⏳ {label}… {remaining}s ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write(f"\r  ⏳ {label}… done{' ' * 5}\n")
    sys.stdout.flush()


def _section_banner(title: str) -> None:
    """Print a prominent section header."""
    print()
    print(f"{'━' * _W}")
    print(f"  {title}")
    print(f"{'━' * _W}")


def _prompt_action(verb: str, mic_name: str) -> None:
    """Print a boxed action prompt with step counter and wait for Enter."""
    global _action_step
    _action_step += 1
    step_label = (
        f"ACTION {_action_step}/{_action_total}" if _action_total else f"ACTION {_action_step}"
    )
    print()
    print(f"╔{'═' * (_W - 2)}╗")
    print(f"║  {step_label:^{_W - 4}}  ║")
    print(f"╠{'═' * (_W - 2)}╣")
    print(f"║  🔌 {verb} {mic_name:<{_W - 10}}║")
    print(f"╚{'═' * (_W - 2)}╝")
    input("  ⏎  Press Enter when ready… ")


def _print_device_info(device: DeviceInfo) -> None:
    """Print formatted device details."""
    print(f"     name       = {device.alsa_name}")
    print(f"     device     = {device.alsa_device}")
    print(f"     stable_id  = {device.stable_device_id}")
    if device.usb_vendor_id:
        print(f"     usb        = VID:{device.usb_vendor_id} PID:{device.usb_product_id}")


def _assert_detected(mic: HwMicConfig, *, expect_count: int = 1) -> list[DeviceInfo]:
    """Assert *mic* is currently detected and return matched devices."""
    devices = _get_usb_devices()
    found = _find_by_config(devices, mic)
    assert len(found) == expect_count, (
        f"Expected exactly {expect_count} {mic.name} "
        f"(VID:{mic.vid} PID:{mic.pid}), "
        f"found {len(found)}. "
        f"All devices: {[d.alsa_name for d in devices]}"
    )
    return found


def _assert_gone(mic: HwMicConfig) -> None:
    """Assert *mic* is NOT detected (after unplug)."""
    devices = _get_usb_devices()
    found = _find_by_config(devices, mic)
    assert len(found) == 0, (
        f"{mic.name} still detected after unplug! Found: {[d.alsa_name for d in found]}"
    )
    print(f"  ✅ {mic.name} — gone (unplug confirmed)")


def _assert_reappeared(mic: HwMicConfig) -> DeviceInfo:
    """Assert *mic* reappeared with a USB-based stable identity."""
    devices = _get_usb_devices()
    found = _find_by_config(devices, mic)
    assert len(found) == 1, (
        f"{mic.name} not found after re-plug! All devices: {[d.alsa_name for d in devices]}"
    )
    device = found[0]
    assert not device.stable_device_id.startswith("alsa-card"), (
        f"Stable ID should use USB identity, not ALSA fallback: {device.stable_device_id}"
    )
    print(f"  ✅ {mic.name} — re-detected")
    _print_device_info(device)
    return device


def _do_unplug(mic: HwMicConfig) -> None:
    """Prompt user to unplug *mic*, wait for settle, assert gone."""
    _prompt_action("UNPLUG", mic.name)
    _settle_wait(_SETTLE_UNPLUG_S, "udev settle")
    _assert_gone(mic)


def _do_replug(mic: HwMicConfig) -> DeviceInfo:
    """Prompt user to re-plug *mic*, wait for settle, assert reappeared."""
    _prompt_action("RE-PLUG", mic.name)
    _settle_wait(_SETTLE_REPLUG_S, "USB enumeration")
    return _assert_reappeared(mic)


# ---------------------------------------------------------------------------
# Test: Dual-Mic Detection (both mics connected simultaneously)
#
# These tests are AUTOMATED (no input() prompts) but are grouped here
# because they require both mics and share helpers with the hot-plug tests.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _BOTH_CONNECTED,
    reason="Dual-mic test requires both primary and secondary mic connected",
)
class TestDualMicDetection:
    """Verify simultaneous detection and matching of two different mic types.

    Skipped unless both primary and secondary mics are physically connected.
    """

    def test_both_mics_detected_simultaneously(self) -> None:
        """Scanner finds both configured mics at the same time."""
        assert SECONDARY_MIC is not None  # guarded by skipif
        _section_banner("Dual-Mic Detection")
        primary = _assert_detected(PRIMARY_MIC)
        secondary = _assert_detected(SECONDARY_MIC)
        print(f"  ✅ {PRIMARY_MIC.name}")
        _print_device_info(primary[0])
        print(f"  ✅ {SECONDARY_MIC.name}")
        _print_device_info(secondary[0])

    async def test_both_mics_matched_to_correct_profiles(
        self,
        seeded_db: async_sessionmaker[AsyncSession],
    ) -> None:
        """Each mic matches its own profile with score 100."""
        assert SECONDARY_MIC is not None

        devices = _get_usb_devices()
        primary = _find_by_config(devices, PRIMARY_MIC)[0]
        secondary = _find_by_config(devices, SECONDARY_MIC)[0]

        matcher = ProfileMatcher()
        async with seeded_db() as session:
            primary_match = await matcher.match(primary, session)
            secondary_match = await matcher.match(secondary, session)

        assert primary_match.score == 100, (
            f"{PRIMARY_MIC.name} should match with score 100, got {primary_match.score}"
        )
        assert primary_match.profile_slug == PRIMARY_MIC.slug, (
            f"Expected slug '{PRIMARY_MIC.slug}', got '{primary_match.profile_slug}'"
        )

        assert secondary_match.score == 100, (
            f"{SECONDARY_MIC.name} should match with score 100, got {secondary_match.score}"
        )
        assert secondary_match.profile_slug == SECONDARY_MIC.slug, (
            f"Expected slug '{SECONDARY_MIC.slug}', got '{secondary_match.profile_slug}'"
        )

        print(
            f"\n  ✅ {PRIMARY_MIC.name} → "
            f"{primary_match.profile_slug} (score={primary_match.score})"
            f"\n  ✅ {SECONDARY_MIC.name} → "
            f"{secondary_match.profile_slug} (score={secondary_match.score})"
        )

    async def test_both_mics_upserted_with_distinct_ids(
        self,
        tmp_path: Path,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Both devices get unique stable_device_ids and distinct DB entries."""
        assert SECONDARY_MIC is not None

        devices = _get_usb_devices()
        primary = _find_by_config(devices, PRIMARY_MIC)[0]
        secondary = _find_by_config(devices, SECONDARY_MIC)[0]

        # Stable IDs must be different
        assert primary.stable_device_id != secondary.stable_device_id, (
            f"Both mics have the same stable_device_id: {primary.stable_device_id}"
        )

        # Both can be upserted
        async with session_factory() as session:
            dev1 = await upsert_device(primary, session)
            dev2 = await upsert_device(secondary, session)
            await session.commit()
            assert dev1.name != dev2.name

        print(
            f"\n  ✅ {PRIMARY_MIC.name} → {primary.stable_device_id}"
            f"\n  ✅ {SECONDARY_MIC.name} → {secondary.stable_device_id}"
        )


# ---------------------------------------------------------------------------
# Test: Single-Mic Hot-Plug (interactive unplug/re-plug)
#
# Skipped when BOTH mics are connected — the dual-mic suite below covers
# the same assertions (disappears, reappears with stable ID) plus
# cross-isolation checks.  Running both would double manual prompts
# without additional coverage.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _PRIMARY_CONNECTED, reason="Primary mic not connected")
@pytest.mark.skipif(
    _BOTH_CONNECTED,
    reason="Covered by TestDualMicHotPlug when both mics present",
)
class TestPrimaryMicHotPlug:
    """Interactive hot-plug tests for the primary microphone.

    These tests run in definition order and require physical interaction:
    1. Verify primary mic is detected.
    2. User unplugs → verify it disappears.
    3. User re-plugs → verify it reappears with same identity.

    Requires ``-s`` flag (stdin capture disabled) for ``input()`` prompts.
    """

    def test_primary_detected_before_unplug(self) -> None:
        """Primary mic must be present before hot-plug sequence."""
        _section_banner(f"Single-Mic Hot-Plug · {PRIMARY_MIC.name}")
        found = _assert_detected(PRIMARY_MIC)
        print(f"  ✅ {PRIMARY_MIC.name} — present")
        _print_device_info(found[0])

    def test_primary_disappears_on_unplug(self) -> None:
        """After unplug, primary mic is gone from scan results."""
        _do_unplug(PRIMARY_MIC)

    def test_primary_reappears_on_replug(self) -> None:
        """After re-plug, primary mic reappears with stable USB identity."""
        _do_replug(PRIMARY_MIC)


@pytest.mark.skipif(
    not _SECONDARY_CONNECTED,
    reason="Secondary mic not configured or not connected",
)
@pytest.mark.skipif(
    _BOTH_CONNECTED,
    reason="Covered by TestDualMicHotPlug when both mics present",
)
class TestSecondaryMicHotPlug:
    """Optional interactive hot-plug tests for the secondary microphone.

    Skipped entirely if:
    - ``SILVASONIC_HW_SECONDARY_PROFILE`` is not set, OR
    - the secondary mic is not physically connected, OR
    - both mics are connected (dual-mic suite covers this).
    """

    def test_secondary_detected_before_unplug(self) -> None:
        """Secondary mic must be present before hot-plug sequence."""
        assert SECONDARY_MIC is not None  # guarded by skipif
        _section_banner(f"Single-Mic Hot-Plug · {SECONDARY_MIC.name}")
        found = _assert_detected(SECONDARY_MIC)
        print(f"  ✅ {SECONDARY_MIC.name} — present")
        _print_device_info(found[0])

    def test_secondary_disappears_on_unplug(self) -> None:
        """After unplug, secondary mic is gone from scan results."""
        assert SECONDARY_MIC is not None
        _do_unplug(SECONDARY_MIC)

    def test_secondary_reappears_on_replug(self) -> None:
        """After re-plug, secondary mic reappears with stable USB identity."""
        assert SECONDARY_MIC is not None
        _do_replug(SECONDARY_MIC)


# ---------------------------------------------------------------------------
# Test: Dual-Mic Hot-Plug (interactive cross-unplug)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _BOTH_CONNECTED,
    reason="Dual hot-plug requires both primary and secondary mic connected",
)
class TestDualMicHotPlug:
    """Interactive dual-mic hot-plug — unplug one while other stays.

    Tests that unplugging one mic does not affect the other.
    Both directions are tested (secondary first, then primary) because
    ALSA card-index renumbering can cause asymmetric behaviour.

    Requires ``-s`` flag for ``input()`` prompts.
    """

    def test_unplug_secondary_primary_survives(self) -> None:
        """Unplug secondary → primary still detected, secondary gone."""
        assert SECONDARY_MIC is not None
        _section_banner("Dual-Mic Hot-Plug · Cross-Isolation")
        _prompt_action("UNPLUG", f"{SECONDARY_MIC.name}  ⚠ ONLY this one!")
        _settle_wait(_SETTLE_UNPLUG_S, "udev settle")

        _assert_gone(SECONDARY_MIC)
        _assert_detected(PRIMARY_MIC)
        print(f"  ✅ Isolation OK — {PRIMARY_MIC.name} survived")

    def test_replug_secondary_both_detected(self) -> None:
        """Re-plug secondary → both mics detected again."""
        assert SECONDARY_MIC is not None
        _do_replug(SECONDARY_MIC)
        _assert_detected(PRIMARY_MIC)
        print(f"  ✅ Both present: {PRIMARY_MIC.name} + {SECONDARY_MIC.name}")

    def test_unplug_primary_secondary_survives(self) -> None:
        """Unplug primary → secondary still detected, primary gone."""
        assert SECONDARY_MIC is not None
        _prompt_action("UNPLUG", f"{PRIMARY_MIC.name}  ⚠ ONLY this one!")
        _settle_wait(_SETTLE_UNPLUG_S, "udev settle")

        _assert_gone(PRIMARY_MIC)
        _assert_detected(SECONDARY_MIC)
        print(f"  ✅ Isolation OK — {SECONDARY_MIC.name} survived")

    def test_replug_primary_both_detected(self) -> None:
        """Re-plug primary → both mics detected with stable IDs."""
        assert SECONDARY_MIC is not None
        device = _do_replug(PRIMARY_MIC)
        sec_found = _assert_detected(SECONDARY_MIC)
        secondary = sec_found[0]

        # Extra: verify both have USB-based stable IDs
        for dev in [device, secondary]:
            assert not dev.stable_device_id.startswith("alsa-card"), (
                f"Stable ID should use USB identity: {dev.stable_device_id}"
            )

        _section_banner("Hot-Plug Complete ✓")
        print(f"  {PRIMARY_MIC.name:<30} id={device.stable_device_id}")
        print(f"  {SECONDARY_MIC.name:<30} id={secondary.stable_device_id}")
