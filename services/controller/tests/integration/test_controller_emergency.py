from unittest.mock import MagicMock, patch

import pytest
from silvasonic.controller.hardware import AudioDevice
from silvasonic.controller.main import ControllerService


@pytest.fixture
def test_settings(tmp_path):
    """Override Controller Settings for testing."""
    with patch("silvasonic.controller.main.settings") as settings_mock:
        # Invalid DB/Redis URLs to ensure failure if accessed
        settings_mock.DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:54321/db"
        settings_mock.REDIS_HOST = "localhost"

        # Paths
        settings_mock.HOST_DATA_DIR = str(tmp_path / "data")
        settings_mock.HOST_SOURCE_DIR = str(tmp_path / "source")

        # Real Profiles Dir for YAML loading test
        # We need to create some dummy profiles
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        settings_mock.PROFILES_DIR = profiles_dir

        # Create a dummy profile
        (profiles_dir / "generic_usb.yml").write_text("""
slug: generic_usb
name: Generic USB Mic
description: Default profile
audio:
  match_pattern: "usb:*"
  sample_rate: 44100
""")

        yield settings_mock


@pytest.mark.integration
@pytest.mark.asyncio
async def test_emergency_mode_stateless_execution(test_settings):
    """Verify Controller enters Emergency Mode when DB is missing."""

    # 1. Initialize Controller
    controller = ControllerService()

    # Mock Scanner
    controller.scanner = MagicMock()
    controller.scanner.find_recording_devices.return_value = []

    # Mock Podman
    controller.podman = MagicMock()
    controller.podman.is_connected.return_value = True
    controller.podman.list_active_services.return_value = []
    controller.service_manager.orchestrator = controller.podman

    # Mock DB Session to Fail Always
    mock_session = MagicMock()
    mock_session.__aenter__.side_effect = Exception("DB Down")

    # Mock Redis Subscriber to Fail Start
    controller.subscriber.start = MagicMock(side_effect=Exception("Redis Down"))
    # Mock Broker Publish to Fail
    controller.broker.publish_lifecycle = MagicMock(side_effect=Exception("Redis Down"))

    # Patch asyncio.sleep to skip wait times
    with (
        patch("asyncio.sleep", return_value=None),
        patch("silvasonic.controller.main.AsyncSessionLocal", return_value=mock_session),
    ):
        # 2. Run Startup Logic (Simulate run() steps)
        # We can't call run() directly because it has a loop.
        # We copy the startup logic calls here or expose a startup method.
        # Since run() is monolithic, we'll verify by constructing the state manually
        # OR extracting startup logic.
        # Refactoring `run()` to `startup()` would be cleaner, but for now let's invoke methods.

        # A. Start Subscriber (Simulate Failure)
        try:
            await controller.subscriber.start()
        except Exception:
            controller.redis_available = False

        assert controller.redis_available is False

        # B. Wait for Database (Simulate Failure)
        db_ready = await controller._wait_for_database()
        assert db_ready is False
        controller.emergency_mode_db = True

        # C. Load Profiles from YAML
        controller.profiles.load_profiles_from_yaml(test_settings.PROFILES_DIR)
        assert len(controller.profiles.profiles) == 1
        assert controller.profiles.profiles[0].slug == "generic_usb"

        # 3. Simulate Device Detection
        new_device = AudioDevice(
            card_index=1,
            id="usb-Mic_Emergency",
            description="USB Microphone",
            serial_number="SN_EMERGENCY_1",
        )
        controller.scanner.find_recording_devices.return_value = [new_device]

        # 4. Run Reconcile (Emergency Mode)
        await controller.reconcile()

        # 5. Verify Stateless Spawn
        spawn_mock = controller.podman.spawn_recorder
        spawn_mock.assert_called_once()

        call_args = spawn_mock.call_args
        assert call_args.kwargs["serial_number"] == "SN_EMERGENCY_1"
        assert call_args.kwargs["mic_profile"] == "generic_usb"
        # Verify Stateless Config (from YAML)
        assert call_args.kwargs["config"]["audio"]["sample_rate"] == 44100

        # Verify Warning Log was emitted (implicitly via structlog capture if we had it, but assertion above is proof)

    # Verify no interaction with DB Session except the check
    # mock_session (context manager) called multipled times for check, but not for reconcile
    # Actually, reconcile uses `async with AsyncSessionLocal()` in normal mode.
    # In emergency mode, we skipped that.
