"""Hardware-dependent system tests — require real USB microphone(s).

Tests the full device detection pipeline with real hardware:
``/proc/asound/cards`` + ``sysfs`` → DeviceScanner → ProfileMatcher → DB.

These tests are **never** included in CI or ``just check-all``.
Run manually with:

    just test-hw

Configuration via environment variables (see ``.env.example``):
- ``SILVASONIC_HW_PRIMARY_PROFILE``   — Primary mic profile slug (default: ``ultramic_384_evo``)
- ``SILVASONIC_HW_SECONDARY_PROFILE`` — Optional secondary mic profile slug

Skip conditions:
- No USB-Audio device detected → all tests skipped
- Primary/secondary mic not connected → respective tests skipped
- Podman socket not available → container tests skipped
- Recorder image not built → container tests skipped
"""

from __future__ import annotations

import contextlib
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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import (
    PODMAN_SOCKET,
    PRIMARY_MIC,
    RECORDER_IMAGE,
    SOCKET_AVAILABLE,
    TEST_RUN_ID,
    HwMicConfig,
    ensure_test_network,
    require_recorder_image,
)

pytestmark = [
    pytest.mark.system_hw,
]


# ---------------------------------------------------------------------------
# Hardware detection helpers
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


# ---------------------------------------------------------------------------
# Test: Real USB Device Detection (any mic)
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
        assert "-" in device_id, f"Expected '{{vendor}}'-'{{product}}'-... format, got: {device_id}"


# ---------------------------------------------------------------------------
# Test: Real Profile Matching with DB (any mic)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _USB_PRESENT, reason="No USB-Audio device connected")
class TestRealProfileMatching:
    """Verify ProfileMatcher against real hardware and DB."""

    async def test_profile_match_with_real_device(
        self,
        seeded_db: async_sessionmaker[AsyncSession],
    ) -> None:
        """Real USB device → ProfileMatcher finds a match in DB."""
        devices = _get_usb_devices()
        assert len(devices) >= 1

        matcher = ProfileMatcher()
        async with seeded_db() as session:
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
# Test: Full Hardware Spawn Cycle (requires Podman + image + primary mic)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _PRIMARY_CONNECTED, reason="Primary mic not connected")
@pytest.mark.skipif(
    not SOCKET_AVAILABLE,
    reason=f"Podman socket not found at {PODMAN_SOCKET}",
)
class TestHardwareSpawnCycle:
    """Full cycle: real USB device → seed → match → evaluate → spawn container."""

    async def test_full_spawn_cycle(
        self,
        tmp_path: Path,
        seeded_db: async_sessionmaker[AsyncSession],
    ) -> None:
        """Detection → matching → DB upsert → evaluation → real container spawn."""
        require_recorder_image()
        ensure_test_network()
        session_factory = seeded_db

        # Scan real hardware — find the primary mic
        devices = _get_usb_devices()
        primary_devices = _find_by_config(devices, PRIMARY_MIC)
        assert len(primary_devices) >= 1
        device_info = primary_devices[0]

        # Match
        matcher = ProfileMatcher()
        async with session_factory() as session:
            match_result = await matcher.match(device_info, session)

        if match_result.score < 100:
            pytest.skip(
                f"Primary mic ({device_info.alsa_name}) did not match "
                f"profile '{PRIMARY_MIC.slug}' (score={match_result.score}). "
                f"Check profile YAML match criteria."
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
        test_name = f"silvasonic-recorder-system-test-hw-spawn-{TEST_RUN_ID}"
        test_spec = Tier2ServiceSpec(
            image=RECORDER_IMAGE,
            name=test_name,
            network=spec.network,
            environment=spec.environment,
            labels={
                **spec.labels,
                "io.silvasonic.test": "system_hw",
                "io.silvasonic.owner": f"controller-test-{TEST_RUN_ID}",
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
            mgr = ContainerManager(client, owner_profile=f"controller-test-{TEST_RUN_ID}")
            info = mgr.start(test_spec)
            assert info is not None, "Container start failed"
            assert info.get("name") == test_name

            # Verify labels
            container = mgr.get(test_name)
            assert container is not None
            labels = container.get("labels", {})
            assert isinstance(labels, dict)
            assert labels.get("io.silvasonic.device_id") == device_info.stable_device_id
            assert labels.get("io.silvasonic.owner") == f"controller-test-{TEST_RUN_ID}"

            # Cleanup
            mgr.stop(test_name, timeout=3)
            mgr.remove(test_name)
        finally:
            with contextlib.suppress(Exception):
                client.containers.get(test_name).remove(force=True)
            client.close()
