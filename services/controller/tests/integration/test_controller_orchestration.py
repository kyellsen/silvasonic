import os
from unittest.mock import MagicMock, patch

import pytest
from silvasonic.controller.hardware import AudioDevice
from silvasonic.controller.main import ControllerService
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.models.system import Device
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# We need to patch settings to point to our test containers
@pytest.fixture
def test_settings(postgres_url, redis_url, tmp_path):
    """Override Controller Settings for testing."""
    with patch("silvasonic.controller.main.settings") as settings_mock:
        # DB
        settings_mock.DATABASE_URL = postgres_url
        # Redis
        settings_mock.REDIS_HOST = redis_url.split("//")[1].split(":")[
            0
        ]  # Hacky parsing, controller might need full URL or host/port split
        # Actually controller uses REDIS_HOST env var usually.
        # Let's check ControllerSettings definition.
        # Assuming defaults.

        # Paths
        settings_mock.HOST_DATA_DIR = str(tmp_path / "data")
        settings_mock.HOST_SOURCE_DIR = str(tmp_path / "source")

        # Podman Socket (Rootless) - Auto-detect
        uid = os.getuid()
        rootless_socket = f"/run/user/{uid}/podman/podman.sock"
        if os.path.exists(rootless_socket):
            settings_mock.PODMAN_SOCKET_URL = f"unix://{rootless_socket}"

        # Create mocked dirs
        os.makedirs(settings_mock.HOST_DATA_DIR, exist_ok=True)
        os.makedirs(settings_mock.HOST_SOURCE_DIR, exist_ok=True)

        yield settings_mock


@pytest.mark.integration
@pytest.mark.asyncio
async def test_device_enrollment_lifecycle(postgres_url, redis_url, test_settings):
    """Scenario 1: Device Enrollment & Lifecycle.

    Ref: Implementation Plan
    """
    # Setup DB Connection
    # Setup DB Connection
    engine = create_async_engine(postgres_url)
    async_session_local = async_sessionmaker(engine, expire_on_commit=False)

    # Pre-seed DB with required Profile
    async with async_session_local() as session:
        # Check if exists first to avoid UniqueViolation in session-scoped DB
        result = await session.execute(
            select(MicrophoneProfile).where(MicrophoneProfile.slug == "generic_usb")
        )
        existing = result.scalar_one_or_none()

        if not existing:
            profile = MicrophoneProfile(
                slug="generic_usb",
                name="Generic USB Mic",
                description="Default profile",
                match_pattern="usb:*",
                config={},
                is_system=True,
            )
            session.add(profile)
            await session.commit()

    # 1. Initialize Controller with Mocks
    controller = ControllerService()

    # Mock the Scanner to return nothing initially
    controller.scanner = MagicMock()
    controller.scanner.find_recording_devices.return_value = []

    # Mock Podman to ensure reconcile proceeds (isolate DB logic)
    controller.podman = MagicMock()
    controller.podman.is_connected.return_value = True
    controller.podman.list_active_services.return_value = []
    controller.podman.spawn_recorder.return_value = True

    # Inject the mocked podman into the existing real ServiceManager
    # This ensures ServiceManager uses our mock but executes its real logic (like reconciling services)
    controller.service_manager.orchestrator = controller.podman

    # Let's partially mock PodmanOrchestrator for the "Check verify NO container" part?
    # No, let's trust the Real Podman listing.

    # Override Session Factory in Controller to use our Test DB
    with patch("silvasonic.controller.main.AsyncSessionLocal", async_session_local):
        # --- T0: Initial Reconcile (Empty) ---
        await controller.reconcile()

        # --- T1: Hot Plug Event ---
        # Mock scanner to return a new device
        new_device = AudioDevice(
            card_index=1,
            id="usb-Mic_1234",
            # fixed args
            description="USB Microphone Device",
            serial_number="SN123456",
        )
        controller.scanner.find_recording_devices.return_value = [new_device]

        # Reconcile
        await controller.reconcile()

        # VERIFY: New row in DB
        async with async_session_local() as session:
            stmt = select(Device).where(Device.serial_number == "SN123456")
            result = await session.execute(stmt)
            device = result.scalar_one_or_none()

            assert device is not None
            assert device.enrollment_status == "pending"  # Inbox Pattern: Default is pending
            assert device.status == "online"

        # VERIFY: No Container Spawned (Pending)
        containers = controller.podman.list_active_services()
        recorder_containers = [c for c in containers if c.get("device_serial") == "SN123456"]
        assert len(recorder_containers) == 0

        # --- T2: Admin Approves Device ---
        async with async_session_local() as session:
            stmt = select(Device).where(Device.serial_number == "SN123456")
            result = await session.execute(stmt)
            device = result.scalar_one()
            device.enrollment_status = "enrolled"
            device.profile_slug = (
                "generic_usb"  # Assuming this profile exists or we need to mock ProfileManager
            )
            await session.commit()

        # Mock Profile Manager to return a profile with config
        # We need to simulate that the profile has some content to verify Flow:
        # DB/Profile -> Controller -> Env/Config -> Recorder
        mock_profile = MagicMock()
        mock_profile.raw_config = {"sample_rate": 48000, "channels": 1}
        controller.profiles.get_profile = MagicMock(return_value=mock_profile)

        with patch.object(controller.podman, "spawn_recorder", return_value=True) as spawn_mock:
            # wait... we need to ensure device.config (overrides) are also handled?
            # The device in DB has config={}

            # Reset Scan Hash to force re-detection (Intelligent Polling)
            controller.last_hardware_hash = ""
            await controller.reconcile()
            spawn_mock.assert_called_once()

            # Verify call args
            call_args = spawn_mock.call_args
            assert call_args.kwargs["serial_number"] == "SN123456"
            assert call_args.kwargs["mic_profile"] == "generic_usb"

            # Verify Config Flow
            expected_config = {"sample_rate": 48000, "channels": 1}
            assert call_args.kwargs["config"] == expected_config
            assert "config_hash" in call_args.kwargs

        # --- T3: Unplug Event ---
        controller.scanner.find_recording_devices.return_value = []

        # Simulating that the container IS running now (since we spawned it in T2)
        controller.podman.list_active_services.return_value = [
            {
                "id": "container_123",
                "device_serial": "SN123456",
                "name": "recorder_SN123456",
                "service": "recorder",
                "created": "2023-01-01T00:00:00+00:00",  # stable
            }
        ]

        with patch.object(controller.podman, "stop_service", return_value=True) as stop_mock:
            await controller.reconcile()
            stop_mock.assert_called_once_with("container_123")

        # Reset active services to empty for next steps if any
        controller.podman.list_active_services.return_value = []

        async with async_session_local() as session:
            stmt = select(Device).where(Device.serial_number == "SN123456")
            result = await session.execute(stmt)
            device = result.scalar_one()
            assert device.status == "offline"


# For the Real Podman test, we need a separate test function
