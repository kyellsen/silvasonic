"""System lifecycle tests — full Controller stack with real Podman.

Tests the complete Controller lifecycle pipeline using:
- Real Podman socket (host-mounted)
- Real PostgreSQL (testcontainers)
- Mocked hardware (/proc/asound/cards)

No real USB microphone required.

Skip conditions:
- Podman socket not available → all tests skipped
- Recorder image not built → container tests skipped

Usage:
    just test-system
    pytest -m system
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import (
    MountSpec,
    RestartPolicy,
    Tier2ServiceSpec,
)
from silvasonic.controller.device_repository import upsert_device
from silvasonic.controller.device_scanner import DeviceScanner, UsbInfo
from silvasonic.controller.podman_client import SilvasonicPodmanClient
from silvasonic.controller.profile_matcher import ProfileMatcher
from silvasonic.controller.reconciler import DeviceStateEvaluator
from silvasonic.controller.seeder import ConfigSeeder, ProfileBootstrapper
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import (
    PODMAN_SOCKET,
    PRIMARY_MIC,
    RECORDER_IMAGE,
    SOCKET_AVAILABLE,
    TEST_RUN_ID,
    make_test_spec,
    require_recorder_image,
    seed_test_defaults,
    seed_test_profile,
)

pytestmark = [
    pytest.mark.system,
]

# Mock ALSA cards: one onboard HDA-Intel, one USB-Audio (primary mic from config)
MOCK_ALSA_ALIAS = PRIMARY_MIC.alsa_contains.replace(" ", "_")[:16]
MOCK_ALSA_FULL_NAME = PRIMARY_MIC.alsa_contains
MOCK_ASOUND_CARDS = (
    " 0 [PCH             ]: HDA-Intel - HDA Intel PCH\n"
    "                      HDA Intel PCH at 0xf7200000 irq 32\n"
    f" 2 [{MOCK_ALSA_ALIAS}]: USB-Audio - {MOCK_ALSA_FULL_NAME}\n"
    f"                      {PRIMARY_MIC.name} at usb-0000:00:14-2\n"
)

MOCK_USB_INFO = UsbInfo(
    vendor_id=PRIMARY_MIC.vid,
    product_id=PRIMARY_MIC.pid,
    serial="SYSTEM-TEST-001",
    bus_path="1-2",
)

MOCK_STABLE_ID = f"{PRIMARY_MIC.vid}-{PRIMARY_MIC.pid}-SYSTEM-TEST-001"


# ---------------------------------------------------------------------------
# Test: Seeding → DB → Device Detection Pipeline (no Podman needed)
# ---------------------------------------------------------------------------


class TestSeedingAndDevicePipeline:
    """Verify seeding + device detection chain with real DB."""

    async def test_seeder_populates_db(
        self,
        tmp_path: Path,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """ConfigSeeder + ProfileBootstrapper insert factory defaults and profiles."""
        defaults_path = seed_test_defaults(tmp_path)
        profiles_dir = seed_test_profile(tmp_path)

        async with session_factory() as session:
            await ConfigSeeder(defaults_path=defaults_path).seed(session)
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        # Verify system config exists
        from silvasonic.core.database.models.system import SystemConfig

        async with session_factory() as session:
            config = await session.get(SystemConfig, "system")
            assert config is not None, "system config should be seeded"
            assert config.value is not None
            assert isinstance(config.value, dict)
            assert config.value.get("auto_enrollment") is True

        # Verify profile exists
        from silvasonic.core.database.models.profiles import MicrophoneProfile

        async with session_factory() as session:
            profile = await session.get(MicrophoneProfile, PRIMARY_MIC.slug)
            assert profile is not None, f"profile '{PRIMARY_MIC.slug}' must be seeded"
            assert profile.name == PRIMARY_MIC.name
            profile_config = profile.config or {}
            assert isinstance(profile_config, dict)
            match_cfg = profile_config.get("audio", {}).get("match", {})
            assert match_cfg.get("usb_vendor_id") == PRIMARY_MIC.vid

    async def test_device_scan_and_profile_match(
        self,
        tmp_path: Path,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Mocked ALSA scan → USB enrichment → profile match → upsert → evaluate."""
        # Seed DB
        defaults_path = seed_test_defaults(tmp_path)
        profiles_dir = seed_test_profile(tmp_path)

        async with session_factory() as session:
            await ConfigSeeder(defaults_path=defaults_path).seed(session)
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        # Scan with mocked /proc/asound/cards
        cards_file = tmp_path / "cards"
        cards_file.write_text(MOCK_ASOUND_CARDS)
        scanner = DeviceScanner(cards_path=cards_file)

        with patch(
            "silvasonic.controller.device_scanner._get_usb_info_for_card",
            return_value=MOCK_USB_INFO,
        ):
            devices = scanner.scan_all()

        assert len(devices) == 1
        info = devices[0]
        assert info.stable_device_id == MOCK_STABLE_ID
        assert PRIMARY_MIC.alsa_contains.lower() in info.alsa_name.lower()

        # Match → auto-enroll
        matcher = ProfileMatcher()
        async with session_factory() as session:
            match_result = await matcher.match(info, session)
        assert match_result.score == 100
        assert match_result.auto_enroll is True
        assert match_result.profile_slug == PRIMARY_MIC.slug

        # Upsert
        async with session_factory() as session:
            device = await upsert_device(
                info,
                session,
                profile_slug=match_result.profile_slug,
                enrollment_status="enrolled",
            )
            await session.commit()
            device_name = device.name
            device_status = device.status

        assert device_name == MOCK_STABLE_ID
        assert device_status == "online"

        # Evaluate → spec
        evaluator = DeviceStateEvaluator()
        async with session_factory() as session:
            specs = await evaluator.evaluate(session)

        matching = [s for s in specs if s.labels.get("io.silvasonic.device_id") == MOCK_STABLE_ID]
        assert len(matching) == 1
        spec = matching[0]
        assert spec.oom_score_adj == -999


# ---------------------------------------------------------------------------
# Test: Real Podman Container Lifecycle (needs socket + image)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not SOCKET_AVAILABLE,
    reason=f"Podman socket not found at {PODMAN_SOCKET}",
)
class TestContainerLifecycle:
    """Verify real Podman container start/stop/reconcile."""

    def test_start_and_stop_recorder(self, tmp_path: Path) -> None:
        """Start a real Recorder container, verify it runs, stop it."""
        require_recorder_image()

        container_name = f"silvasonic-recorder-system-test-lifecycle-{TEST_RUN_ID}"
        workspace = tmp_path / "recorder" / "lifecycle"
        workspace.mkdir(parents=True, exist_ok=True)
        spec = make_test_spec(container_name, "system-test-lifecycle", workspace)

        client = SilvasonicPodmanClient(
            socket_path=PODMAN_SOCKET,
            max_retries=2,
            retry_delay=0.5,
        )
        client.connect()

        try:
            mgr = ContainerManager(client, owner_profile=f"controller-test-{TEST_RUN_ID}")

            # Start
            info = mgr.start(spec)
            assert info is not None, "start() must return container info"
            assert info.get("name") == container_name

            # Verify running
            running = mgr.get(container_name)
            assert running is not None, "Container must be visible after start"

            # Appears in list_managed
            managed = mgr.list_managed()
            managed_names = [str(c.get("name", "")) for c in managed]
            assert container_name in managed_names

            # Stop
            assert mgr.stop(container_name) is True
            # Remove
            assert mgr.remove(container_name) is True
            assert mgr.get(container_name) is None
        finally:
            with contextlib.suppress(Exception):
                client.containers.get(container_name).remove(force=True)
            client.close()

    def test_sync_state_starts_and_stops(self, tmp_path: Path) -> None:
        """sync_state() starts missing and stops orphaned containers."""
        require_recorder_image()

        name_desired = f"silvasonic-recorder-system-test-desired-{TEST_RUN_ID}"
        name_orphan = f"silvasonic-recorder-system-test-orphan-{TEST_RUN_ID}"

        workspace_d = tmp_path / "recorder" / "desired"
        workspace_d.mkdir(parents=True, exist_ok=True)
        workspace_o = tmp_path / "recorder" / "orphan"
        workspace_o.mkdir(parents=True, exist_ok=True)

        spec_desired = make_test_spec(name_desired, "desired-device", workspace_d)
        spec_orphan = make_test_spec(name_orphan, "orphan-device", workspace_o)

        client = SilvasonicPodmanClient(
            socket_path=PODMAN_SOCKET,
            max_retries=2,
            retry_delay=0.5,
        )
        client.connect()

        try:
            mgr = ContainerManager(client, owner_profile=f"controller-test-{TEST_RUN_ID}")

            # Pre-start the orphan (it should be stopped by sync_state)
            mgr.start(spec_orphan)
            assert mgr.get(name_orphan) is not None

            # Sync: desired = [spec_desired], actual = [orphan running]
            actual = mgr.list_managed()
            mgr.sync_state(desired=[spec_desired], actual=actual)

            # Desired should now be running
            assert mgr.get(name_desired) is not None, "desired must be started"
            # Orphan should be stopped and removed
            assert mgr.get(name_orphan) is None, "orphan must be removed"

            # Cleanup
            mgr.stop(name_desired)
            mgr.remove(name_desired)
        finally:
            for name in [name_desired, name_orphan]:
                with contextlib.suppress(Exception):
                    client.containers.get(name).remove(force=True)
            client.close()

    def test_graceful_shutdown_stops_all(self, tmp_path: Path) -> None:
        """Simulated graceful shutdown stops all managed containers."""
        require_recorder_image()

        names = [
            f"silvasonic-recorder-system-test-shutdown-a-{TEST_RUN_ID}",
            f"silvasonic-recorder-system-test-shutdown-b-{TEST_RUN_ID}",
        ]

        client = SilvasonicPodmanClient(
            socket_path=PODMAN_SOCKET,
            max_retries=2,
            retry_delay=0.5,
        )
        client.connect()

        try:
            mgr = ContainerManager(client, owner_profile=f"controller-test-{TEST_RUN_ID}")
            for i, name in enumerate(names):
                workspace = tmp_path / "recorder" / f"shutdown-{i}"
                workspace.mkdir(parents=True, exist_ok=True)
                spec = make_test_spec(name, f"shutdown-device-{i}", workspace)
                mgr.start(spec)

            # Verify both running
            managed = mgr.list_managed()
            managed_names = [str(c.get("name", "")) for c in managed]
            for name in names:
                assert name in managed_names

            # Shutdown: stop all (like ControllerService._stop_all_tier2)
            for c in managed:
                cname = str(c.get("name", ""))
                if cname in names:
                    mgr.stop(cname)
                    mgr.remove(cname)

            # Verify gone
            for name in names:
                assert mgr.get(name) is None
        finally:
            for name in names:
                with contextlib.suppress(Exception):
                    client.containers.get(name).remove(force=True)
            client.close()


# ---------------------------------------------------------------------------
# Test: Mock-Source Recorder Capture (no real hardware needed)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not SOCKET_AVAILABLE,
    reason=f"Podman socket not found at {PODMAN_SOCKET}",
)
class TestRecorderMockCapture:
    """Verify Recorder container produces WAV files using mock audio source.

    Uses ``SILVASONIC_RECORDER_MOCK_SOURCE=true`` so no real USB microphone
    is required. The Recorder generates synthetic 440 Hz sine-wave audio
    and writes segmented WAV files to the bind-mounted workspace.

    This closes the critical gap where system tests previously started
    Recorder containers but never verified WAV output.
    """

    def test_mock_source_produces_wav(self, tmp_path: Path) -> None:
        """Container with mock_source produces WAV files in workspace."""
        import wave

        require_recorder_image()

        container_name = f"silvasonic-recorder-system-test-mock-capture-{TEST_RUN_ID}"
        workspace = tmp_path / "recorder" / "mock-capture"
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o777)

        spec = Tier2ServiceSpec(
            image=RECORDER_IMAGE,
            name=container_name,
            network="silvasonic-net",
            environment={
                "SILVASONIC_RECORDER_DEVICE": "hw:99,0",
                "SILVASONIC_RECORDER_MOCK_SOURCE": "true",
                "SILVASONIC_REDIS_URL": "redis://silvasonic-redis:6379/0",
                "SILVASONIC_RECORDER_WORKSPACE": "/app/workspace",
            },
            labels={
                "io.silvasonic.tier": "2",
                "io.silvasonic.owner": f"controller-test-{TEST_RUN_ID}",
                "io.silvasonic.service": "recorder",
                "io.silvasonic.device_id": "mock-capture-test",
                "io.silvasonic.test": "system",
            },
            mounts=[
                MountSpec(
                    source=str(workspace),
                    target="/app/workspace",
                    read_only=False,
                ),
            ],
            devices=[],
            group_add=[],
            privileged=False,
            restart_policy=RestartPolicy(name="no", max_retry_count=0),
            memory_limit="256m",
            cpu_limit=1.0,
            oom_score_adj=-999,
        )

        client = SilvasonicPodmanClient(
            socket_path=PODMAN_SOCKET,
            max_retries=2,
            retry_delay=0.5,
        )
        client.connect()

        try:
            mgr = ContainerManager(client, owner_profile=f"controller-test-{TEST_RUN_ID}")
            info = mgr.start(spec)
            assert info is not None, "Container start failed"

            # Wait for the Recorder to produce at least 1 full segment
            # Default segment=10s, wait 15s to ensure at least 1 promoted
            wait_seconds = 15
            time.sleep(wait_seconds)

            # Stop gracefully (promotes final segment)
            mgr.stop(container_name, timeout=10)

            # Verify WAV files in workspace
            data_dir = workspace / "data" / "raw"
            buffer_dir = workspace / ".buffer" / "raw"

            wav_in_data = list(data_dir.glob("*.wav")) if data_dir.exists() else []
            wav_in_buffer = list(buffer_dir.glob("*.wav")) if buffer_dir.exists() else []
            total_wavs = len(wav_in_data) + len(wav_in_buffer)

            if total_wavs < 1:
                # Capture logs for debugging
                try:
                    import subprocess

                    logs = subprocess.run(
                        ["podman", "logs", container_name],
                        capture_output=True,
                        text=True,
                    )
                    print(
                        f"\n--- CONTAINER LOGS ({container_name}) ---\n"
                        f"{logs.stderr}\n{logs.stdout}\n"
                        "----------------------------------"
                    )
                except Exception as e:
                    print(f"Could not fetch podman logs: {e}")

            assert total_wavs >= 1, (
                f"No WAV files found in workspace {workspace}. "
                f"data/raw: {wav_in_data}, .buffer/raw: {wav_in_buffer}. "
                f"Check container logs with: podman logs {container_name}"
            )

            # Validate WAV file(s) are actual audio (stdlib wave module)
            for wav_path in wav_in_data:
                with wave.open(str(wav_path), "rb") as wf:
                    assert wf.getnframes() > 0, f"WAV {wav_path.name} has 0 frames"
                    assert wf.getframerate() > 0
                    assert wf.getnchannels() >= 1

            mgr.remove(container_name)
        finally:
            with contextlib.suppress(Exception):
                client.containers.get(container_name).remove(force=True)
            client.close()
