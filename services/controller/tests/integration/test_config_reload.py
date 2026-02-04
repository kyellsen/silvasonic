import asyncio
from collections.abc import Generator
from unittest.mock import patch

import pytest
from silvasonic.controller.main import ControllerService
from silvasonic.core.redis.publisher import RedisPublisher
from silvasonic.core.redis.settings import RedisSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="module")
def redis_container() -> Generator[RedisContainer, None, None]:
    """Spin up Redis container."""
    with RedisContainer("redis:7-alpine") as redis:
        yield redis


@pytest.fixture
def redis_settings(redis_container: RedisContainer) -> RedisSettings:
    """Return RedisSettings pointing to the container."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return RedisSettings(
        redis_host=host,
        redis_port=port,
        redis_password=None,
    )


@pytest.fixture
def postgres_url_str(postgres_url: str) -> str:
    """Helper to get string only from the async generator/fixture if needed or just pass through."""
    # The existing fixture in conftest.py returns a string generator?
    # conftest.py: yield f"postgresql+asyncpg://..."
    return postgres_url


@pytest.mark.asyncio
async def test_config_reload_integration(
    redis_container: RedisContainer,
    redis_settings: RedisSettings,
    postgres_url: str,
    tmp_path,
    caplog,
) -> None:
    """End-to-End Integration Test for Controller Config Reload.

    Verifies that:
    1. A 'reload_mic_profiles_from_db' command sent via Redis is received by the Controller.
    2. The Controller executes the reload logic (logs 'mic_profiles_reloaded').
    3. A 'reset_mic_profiles_to_defaults' command works similarly.
    """
    # 0. Setup Settings Patches
    # We need to patch Redis settings so Controller connects to our container
    # We also mock Podman/Scanner to avoid system calls

    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    (profile_dir / "integration_mic.yml").write_text("""
slug: "integration_mic"
name: "Original Name"
description: "Integration Test"
audio:
    match_pattern: "TestDevice.*"
""")

    engine = create_async_engine(postgres_url)

    with (
        patch("silvasonic.core.redis.client.settings", redis_settings),
        patch("silvasonic.controller.main.settings") as main_settings,
        patch("silvasonic.controller.main.PodmanOrchestrator"),
        patch("silvasonic.controller.main.DeviceScanner"),
    ):
        # Configure Profile Dir for Bootstrap
        main_settings.PROFILES_DIR = str(profile_dir)

        # 1. Initialize Controller
        service = ControllerService()
        # Override DB Session to use test container
        from sqlalchemy.ext.asyncio import async_sessionmaker

        test_session_factory = async_sessionmaker(engine, expire_on_commit=False)
        service.profiles.session_factory = (
            test_session_factory  # This might not be how it works, let's check profile manager
        )
        # ProfileManager doesn't hold session factory, it takes session in methods.
        # But ControllerService instantiates AsyncSessionLocal in run() and handlers.
        # We need to patch AsyncSessionLocal in silvasonic.controller.main

    # Re-entering patch context with AsyncSessionLocal patched
    with (
        patch("silvasonic.core.redis.client.settings", redis_settings),
        patch("silvasonic.controller.main.settings") as main_settings,
        patch("silvasonic.controller.main.PodmanOrchestrator"),
        patch("silvasonic.controller.main.DeviceScanner"),
        patch(
            "silvasonic.controller.main.AsyncSessionLocal", test_session_factory
        ),  # Patch main.py usage
        patch(
            "silvasonic.controller.bootstrap.AsyncSessionLocal", test_session_factory
        ),  # Patch bootstrap usage
    ):
        main_settings.PROFILES_DIR = str(profile_dir)
        main_settings.SYNC_INTERVAL_SECONDS = 1

        # Start Controller in Background Task
        # We need to start it, but wait for it to be ready.
        # service.run() has an infinite loop.

        service = ControllerService()

        # Run it!
        controller_task = asyncio.create_task(service.run())

        # Wait for "controller_service_started" log or similar
        # Or just sleep briefly
        await asyncio.sleep(2.0)

        # 2. Setup External Publisher (Simulating UI/Admin)
        publisher = RedisPublisher(service_name="admin_ui", instance_id="integration_test")

        # --- SCENARIO A: Reload from DB ---
        print("\n🔵 Scenario A: Reload from DB")

        # Verify initial state (should be empty in RAM because DB is empty initially?)
        # Actually ProfileBootstrapper runs on start of service.run()
        # It should have loaded "integration_mic"

        # Let's verify via Log or by inspecting service (if possible, but thread safety...)
        # service.profiles.profiles is likely populated.
        assert len(service.profiles.profiles) == 1
        assert service.profiles.profiles[0].name == "Original Name"

        # Manipulate DB directly
        async with test_session_factory() as session:
            await session.execute(
                text(
                    "UPDATE microphone_profiles SET name = 'DB Updated Name' WHERE slug = 'integration_mic'"
                )
            )
            await session.commit()

        # Send Command
        await publisher.publish_control(
            command="reload_mic_profiles_from_db",
            initiator="test_case",
            target_service="controller",
        )

        # Wait for propagation
        # We look for "mic_profiles_reloaded" log
        # Wait for propagation by polling state
        # We verify that RAM state updates to match DB
        updated = False
        for _ in range(20):  # 2 seconds max
            profile = service.profiles.get_profile("integration_mic")
            if profile and profile.name == "DB Updated Name":
                updated = True
                break
            await asyncio.sleep(0.1)

        assert updated, "Controller did not update profile name in RAM after reload"

        # Verify RAM state
        profile = service.profiles.get_profile("integration_mic")
        assert profile.name == "DB Updated Name"

        # --- SCENARIO B: Reset to Defaults ---
        print("\n🔵 Scenario B: Reset to Defaults")

        # Clear logs to check for new message
        caplog.clear()

        # Send Command
        await publisher.publish_control(
            command="reset_mic_profiles_to_defaults",
            initiator="test_case",
            target_service="controller",
        )

        # Wait for propagation
        # We look for "mic_profiles_reset_complete" log
        # Wait for propagation
        reset_complete = False
        for _ in range(20):
            profile = service.profiles.get_profile("integration_mic")
            if profile and profile.name == "Original Name":
                reset_complete = True
                break
            await asyncio.sleep(0.1)

        assert reset_complete, "Controller did not reset profile name to Original Name"

        # Verify RAM state (Should be back to "Original Name")
        profile = service.profiles.get_profile("integration_mic")
        assert profile.name == "Original Name"

        # Clean up
        controller_task.cancel()
        try:
            await controller_task
        except asyncio.CancelledError:
            pass
