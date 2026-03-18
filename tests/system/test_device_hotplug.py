"""Hardware-dependent system tests — require a real USB microphone.

Tests the full device detection pipeline with real hardware:
``/proc/asound/cards`` + ``sysfs`` → DeviceScanner → ProfileMatcher → DB.

These tests are **never** included in CI or ``just check-all``.
Run manually with:

    just test-hw

Skip conditions:
- No USB-Audio device detected → all tests skipped
- Podman socket not available → container tests skipped
- Recorder image not built → container tests skipped
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import (
    MountSpec,
    RestartPolicy,
    Tier2ServiceSpec,
)
from silvasonic.controller.device_scanner import DeviceInfo, DeviceScanner, upsert_device
from silvasonic.controller.podman_client import SilvasonicPodmanClient
from silvasonic.controller.profile_matcher import ProfileMatcher
from silvasonic.controller.reconciler import DeviceStateEvaluator
from silvasonic.controller.seeder import ConfigSeeder, ProfileBootstrapper
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import (
    PODMAN_SOCKET,
    RECORDER_IMAGE,
    SOCKET_AVAILABLE,
    require_recorder_image,
    seed_test_defaults,
    seed_test_profile,
)

pytestmark = [
    pytest.mark.system_hw,
]


# ---------------------------------------------------------------------------
# Hardware detection helper
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


_USB_PRESENT = _has_usb_audio_device()


# ---------------------------------------------------------------------------
# Test: Real USB Device Detection
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _USB_PRESENT, reason="No USB-Audio device connected")
class TestRealDeviceDetection:
    """Verify DeviceScanner against real hardware."""

    def test_scanner_finds_usb_device(self) -> None:
        """DeviceScanner.scan_all() detects at least one USB-Audio device."""
        devices = _get_usb_devices()
        assert len(devices) >= 1, "Expected at least 1 USB-Audio device in /proc/asound/cards"

        device = devices[0]
        assert device.alsa_card_index >= 0
        assert device.alsa_name, "ALSA name must not be empty"
        assert device.alsa_device.startswith("hw:"), (
            f"Expected 'hw:N,0', got '{device.alsa_device}'"
        )

    def test_usb_info_populated_from_sysfs(self) -> None:
        """DeviceScanner populates USB vendor/product info from sysfs."""
        devices = _get_usb_devices()
        assert len(devices) >= 1

        device = devices[0]
        # Real USB devices should have at least vendor and product IDs
        assert device.usb_vendor_id is not None, f"USB vendor ID missing for {device.alsa_name}"
        assert device.usb_product_id is not None, f"USB product ID missing for {device.alsa_name}"

    def test_stable_device_id_uses_usb_identity(self) -> None:
        """Stable device ID is based on USB identity, not ALSA card index."""
        devices = _get_usb_devices()
        assert len(devices) >= 1

        device = devices[0]
        device_id = device.stable_device_id

        # With real USB, should be vendor-product-serial or vendor-product-portN
        assert not device_id.startswith("alsa-card"), (
            f"Real USB device should not use ALSA fallback: {device_id}"
        )
        assert "-" in device_id, (
            f"Expected '{'{vendor}'}'-'{'{product}'}'-... format, got: {device_id}"
        )


# ---------------------------------------------------------------------------
# Test: Real Profile Matching with DB
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _USB_PRESENT, reason="No USB-Audio device connected")
class TestRealProfileMatching:
    """Verify ProfileMatcher against real hardware and DB."""

    async def test_profile_match_with_real_device(
        self,
        tmp_path: Path,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Real USB device → ProfileMatcher finds a match in DB."""
        # Seed profiles
        defaults_path = seed_test_defaults(tmp_path)
        profiles_dir = seed_test_profile(tmp_path)

        async with session_factory() as session:
            await ConfigSeeder(defaults_path=defaults_path).seed(session)
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        # Scan real hardware
        devices = _get_usb_devices()
        assert len(devices) >= 1

        matcher = ProfileMatcher()
        async with session_factory() as session:
            match_result = await matcher.match(devices[0], session)

        # We can't guarantee a match (depends on which mic is connected),
        # but the matcher must not crash and must return a valid MatchResult.
        assert match_result.score >= 0
        assert match_result.score in {0, 50, 100}

    async def test_upsert_real_device_to_db(
        self,
        tmp_path: Path,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Real USB device can be upserted into the devices table."""
        devices = _get_usb_devices()
        assert len(devices) >= 1

        device_info = devices[0]
        async with session_factory() as session:
            device = await upsert_device(device_info, session)
            await session.commit()
            assert device.name == device_info.stable_device_id
            assert device.status == "online"
            assert device.model == device_info.alsa_name


# ---------------------------------------------------------------------------
# Test: Full Hardware Spawn Cycle (requires Podman + image + USB mic)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _USB_PRESENT, reason="No USB-Audio device connected")
@pytest.mark.skipif(
    not SOCKET_AVAILABLE,
    reason=f"Podman socket not found at {PODMAN_SOCKET}",
)
class TestHardwareSpawnCycle:
    """Full cycle: real USB device → seed → match → evaluate → spawn container."""

    async def test_full_spawn_cycle(
        self,
        tmp_path: Path,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Detection → matching → DB upsert → evaluation → real container spawn."""
        require_recorder_image()

        # Seed DB
        defaults_path = seed_test_defaults(tmp_path)
        profiles_dir = seed_test_profile(tmp_path)

        async with session_factory() as session:
            await ConfigSeeder(defaults_path=defaults_path).seed(session)
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        # Scan real hardware
        devices = _get_usb_devices()
        assert len(devices) >= 1
        device_info = devices[0]

        # Match
        matcher = ProfileMatcher()
        async with session_factory() as session:
            match_result = await matcher.match(device_info, session)

        if match_result.score < 100:
            pytest.skip(
                f"Connected device ({device_info.alsa_name}) did not match "
                f"any seeded profile (score={match_result.score}). "
                f"This test requires a device with a matching profile."
            )

        # Upsert as enrolled
        async with session_factory() as session:
            await upsert_device(
                device_info,
                session,
                profile_slug=match_result.profile_slug,
                enrollment_status="enrolled",
            )
            await session.commit()

        # Evaluate
        evaluator = DeviceStateEvaluator()
        async with session_factory() as session:
            specs = await evaluator.evaluate(session)

        matching = [
            s
            for s in specs
            if s.labels.get("io.silvasonic.device_id") == device_info.stable_device_id
        ]
        assert len(matching) == 1, (
            f"Expected 1 spec for {device_info.stable_device_id}, got {len(matching)}"
        )

        # Spawn a real container (using a minimal test spec to avoid /dev/snd issues)
        spec = matching[0]
        test_name = "silvasonic-recorder-system-test-hw-spawn"
        test_spec = Tier2ServiceSpec(
            image=RECORDER_IMAGE,
            name=test_name,
            network=spec.network,
            environment=spec.environment,
            labels={
                **spec.labels,
                "io.silvasonic.test": "system_hw",  # Extra label for test identification
            },
            mounts=[
                MountSpec(
                    source=str(tmp_path / "recorder" / "hw-spawn"),
                    target="/app/workspace",
                    read_only=False,
                ),
            ],
            devices=[],  # Don't pass /dev/snd in test — Recorder starts without audio
            group_add=[],
            privileged=False,
            restart_policy=RestartPolicy(name="no", max_retry_count=0),
            memory_limit="128m",
            cpu_limit=0.5,
            oom_score_adj=-999,
        )
        (tmp_path / "recorder" / "hw-spawn").mkdir(parents=True, exist_ok=True)

        client = SilvasonicPodmanClient(
            socket_path=PODMAN_SOCKET,
            max_retries=2,
            retry_delay=0.5,
        )
        client.connect()

        try:
            mgr = ContainerManager(client)
            info = mgr.start(test_spec)
            assert info is not None, "Container start failed"
            assert info.get("name") == test_name

            # Verify labels
            container = mgr.get(test_name)
            assert container is not None
            labels = container.get("labels", {})
            assert isinstance(labels, dict)
            assert labels.get("io.silvasonic.device_id") == device_info.stable_device_id
            assert labels.get("io.silvasonic.owner") == "controller"

            # Cleanup
            mgr.stop(test_name, timeout=3)
            mgr.remove(test_name)
        finally:
            with contextlib.suppress(Exception):
                client.containers.get(test_name).remove(force=True)
            client.close()


# ---------------------------------------------------------------------------
# Test: Interactive UltraMic 384K Hot-Plug (user must unplug/re-plug)
# ---------------------------------------------------------------------------

_ULTRAMIC_VID = "0869"
_ULTRAMIC_PID = "0389"


def _find_ultramic(devices: list[DeviceInfo]) -> list[DeviceInfo]:
    """Filter devices to UltraMic 384K by USB VID/PID."""
    return [
        d for d in devices if d.usb_vendor_id == _ULTRAMIC_VID and d.usb_product_id == _ULTRAMIC_PID
    ]


@pytest.mark.skipif(not _USB_PRESENT, reason="No USB-Audio device connected")
class TestUltraMicHotPlug:
    """Interactive hot-plug tests — user unplugs/re-plugs UltraMic 384K.

    These tests run in definition order and require physical interaction:
    1. Verify UltraMic is detected.
    2. User unplugs → verify it disappears.
    3. User re-plugs → verify it reappears with same identity.

    Requires ``-s`` flag (stdin capture disabled) for ``input()`` prompts.
    """

    def test_ultramic_detected_before_unplug(self) -> None:
        """UltraMic 384K must be present before hot-plug sequence."""
        devices = _get_usb_devices()
        ultramic = _find_ultramic(devices)
        assert len(ultramic) == 1, (
            f"Expected exactly 1 UltraMic 384K "
            f"(VID:{_ULTRAMIC_VID} PID:{_ULTRAMIC_PID}), "
            f"found {len(ultramic)}. "
            f"All devices: {[d.alsa_name for d in devices]}"
        )
        print(f"\n  ✅ UltraMic detected: {ultramic[0].alsa_name} ({ultramic[0].alsa_device})")

    def test_ultramic_disappears_on_unplug(self) -> None:
        """After unplug, UltraMic is gone from scan results."""
        print("\n" + "─" * 50)
        print("  🔌 Bitte UltraMic 384K JETZT ABZIEHEN")
        input("     Dann Enter drücken... ")
        print("─" * 50)

        time.sleep(2)  # udev/ALSA settle time

        devices = _get_usb_devices()
        ultramic = _find_ultramic(devices)
        assert len(ultramic) == 0, (
            f"UltraMic 384K still detected after unplug! Found: {[d.alsa_name for d in ultramic]}"
        )
        print("  ✅ UltraMic no longer detected — unplug confirmed.")

    def test_ultramic_reappears_on_replug(self) -> None:
        """After re-plug, UltraMic reappears with stable USB identity."""
        print("\n" + "─" * 50)
        print("  🔌 Bitte UltraMic 384K JETZT WIEDER ANSTECKEN")
        input("     Dann Enter drücken... ")
        print("─" * 50)

        time.sleep(3)  # USB enumeration takes a moment

        devices = _get_usb_devices()
        ultramic = _find_ultramic(devices)
        assert len(ultramic) == 1, (
            f"UltraMic 384K not found after re-plug! All devices: {[d.alsa_name for d in devices]}"
        )

        device = ultramic[0]
        # Verify stable identity uses USB, not ALSA fallback
        assert not device.stable_device_id.startswith("alsa-card"), (
            f"Stable ID should use USB identity, not ALSA fallback: {device.stable_device_id}"
        )
        print(
            f"  ✅ UltraMic re-detected: {device.alsa_name} "
            f"({device.alsa_device}) — "
            f"stable_id={device.stable_device_id}"
        )
