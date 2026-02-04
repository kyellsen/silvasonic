import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from silvasonic.controller.hardware import AudioDevice
from silvasonic.controller.main import ControllerService
from silvasonic.core.schemas.control import ControlMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_configuration_lifecycle(postgres_url, tmp_path, monkeypatch):
    """Controller Service Integration Test: Configuration Lifecycle

    Verifies the Controller's ability to manage configuration across three scenarios:
    1. Cold Start (Injection)
    2. Hot Reload (DB -> RAM)
    3. Factory Reset (YAML -> DB -> RAM)
    """
    # --- SETUP ---

    # 0. Setup Database Connection
    test_engine = create_async_engine(postgres_url)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    # 1. Setup Filesystem (YAML)
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    (profile_dir / "lifecycle_mic.yml").write_text("""
slug: "lifecycle_mic"
name: "Original Name"
description: "Original Description"
audio:
    match_pattern: "TestDevice.*"
    sample_rate: 44100
    format: "S16LE"
""")

    # 2. Setup Bootstrapper Factory
    from silvasonic.controller.bootstrap import ProfileBootstrapper as RealBootstrapper

    def bootstrapper_factory(*args, **kwargs):
        # Always inject our temp profiles dir
        return RealBootstrapper(profiles_dir=str(profile_dir))

    # 3. Setup Dependencies Mocks
    with (
        patch("silvasonic.controller.main.PodmanOrchestrator") as mock_podman_cls,
        patch("silvasonic.controller.main.DeviceScanner") as mock_scanner_cls,
        patch("silvasonic.controller.main.MessageBroker") as mock_broker_cls,
        patch("silvasonic.controller.main.RedisSubscriber") as mock_sub_cls,
        patch("silvasonic.controller.main.ProfileBootstrapper", side_effect=bootstrapper_factory),
        patch("silvasonic.controller.bootstrap.AsyncSessionLocal", test_session_factory),
        patch("silvasonic.controller.main.AsyncSessionLocal", test_session_factory),
    ):
        # Configure Mocks
        mock_podman = mock_podman_cls.return_value
        mock_podman.is_connected.return_value = True
        mock_podman.spawn_recorder.return_value = True
        mock_podman.list_active_services.return_value = []

        mock_scanner = mock_scanner_cls.return_value

        # Prevent network calls with AsyncMock for awaitables
        mock_broker_cls.return_value.publish_status = AsyncMock(return_value=None)
        mock_broker_cls.return_value.publish_lifecycle = AsyncMock(return_value=None)
        mock_sub_cls.return_value.start = AsyncMock(return_value=None)
        mock_sub_cls.return_value.stop = AsyncMock(return_value=None)

        # Initialize Service
        service = ControllerService()

        # Capture the handlers registered to Subscriber
        registered_handlers = {}

        def mock_register(cmd, handler):
            registered_handlers[cmd] = handler

        mock_sub_cls.return_value.register_handler.side_effect = mock_register

        # Start service (activates subscriber) in background
        server_task = asyncio.create_task(service.run())
        # Yield to allow startup
        await asyncio.sleep(1)

        # --- SCENARIO 1: COLD START (Injection) ---
        print("\n🔵 Starting Scenario 1: Cold Start")

        # 1.1 Bootstrap (Sync YAML -> DB) -- Logic manually triggered or assumed to run
        # In production, bootstrap runs on app startup separate from service.run
        bootstrapper = RealBootstrapper(profiles_dir=str(profile_dir))
        await bootstrapper.sync()

        # 1.2 Load (DB -> RAM)
        async with test_session_factory() as session:
            await service.profiles.load_profiles(session)

        # 1.3 Verify Injection
        test_device = AudioDevice(
            card_index=1, id="HW1", description="TestDevice X", serial_number="SN_1"
        )
        mock_scanner.find_recording_devices.return_value = [test_device]

        await service.reconcile()

        mock_podman.spawn_recorder.assert_called()
        call_args = mock_podman.spawn_recorder.call_args[1]
        assert call_args["config"]["name"] == "Original Name"

        print("✅ Scenario 1 Passed")

        # --- SCENARIO 2: HOT RELOAD ---
        print("🔵 Starting Scenario 2: Hot Reload")

        # 2.1 Admin updates DB directly (simulate UI change)
        async with test_session_factory() as session:
            await session.execute(
                text(
                    "UPDATE microphone_profiles SET name = 'Renamed via UI' WHERE slug = 'lifecycle_mic'"
                )
            )
            await session.commit()

        # 2.2 Trigger Reload Command
        reload_msg = ControlMessage(
            command="reload_mic_profiles_from_db",
            initiator="admin_ui",
            target_service="controller",
            target_instance="main",
            payload={},
        )
        await registered_handlers["reload_mic_profiles_from_db"](reload_msg)

        # 2.3 Verify Controller Memory Updated
        profile = service.profiles.get_profile("lifecycle_mic")
        assert profile.name == "Renamed via UI"

        # 2.4 Verify Reconcile picks up the change (Restart)
        old_hash = call_args["config_hash"]  # from previous spawn

        mock_podman.list_active_services.return_value = [
            {
                "id": "container_1",
                "device_serial": "SN_1",
                "labels": {"silvasonic.config_hash": old_hash},  # Old hash
            }
        ]

        # Setup Stop/Start Expectations
        mock_podman.stop_service.return_value = True
        mock_podman.spawn_recorder.reset_mock()

        await service.reconcile()

        # Should stop old container
        mock_podman.stop_service.assert_called_with("container_1")

        # Should start new container with NEW config
        mock_podman.spawn_recorder.assert_called()
        new_call_args = mock_podman.spawn_recorder.call_args[1]
        assert new_call_args["config"]["name"] == "Renamed via UI"
        assert new_call_args["config_hash"] != old_hash

        print("✅ Scenario 2 Passed")

        # --- SCENARIO 3: FACTORY RESET ---
        print("🔵 Starting Scenario 3: Factory Reset")

        # 3.1 Simulate Data Corruption (Delete from DB)
        async with test_session_factory() as session:
            await session.execute(text("DELETE FROM microphone_profiles"))
            await session.commit()

        # 3.2 Trigger Reset Command
        # This should uses ProfileBootstrapper (patched settings) to re-read YAML -> DB -> RAM
        reset_msg = ControlMessage(
            command="reset_mic_profiles_to_defaults",
            initiator="admin_ui",
            target_service="controller",
            target_instance="main",
            payload={},
        )
        await registered_handlers["reset_mic_profiles_to_defaults"](reset_msg)

        # 3.3 Verify Restoration
        # Memory check
        profile = service.profiles.get_profile("lifecycle_mic")
        assert profile.name == "Original Name"  # Back to YAML value

        # DB Check
        async with test_session_factory() as session:
            res = await session.execute(
                text("SELECT name FROM microphone_profiles WHERE slug = 'lifecycle_mic'")
            )
            row = res.one()
            assert row.name == "Original Name"

        print("✅ Scenario 3 Passed")

        # Cleanup
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
