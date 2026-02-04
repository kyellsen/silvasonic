import asyncio
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from silvasonic.controller.hardware import AudioDevice
from silvasonic.controller.main import ControllerService
from silvasonic.core.database.models.profiles import MicrophoneProfile
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_identity_persistence_replug(tmp_path):
    """Identity Persistence Test:
    1. Start Infrastructure.
    2. Connect Device A -> Verify Recording starts in `data/recorder/generic_usb-<serial_short>/`.
    3. Disconnect Device A -> Verify Recorder stops.
    4. Connect Device A AGAIN -> Verify Recorder starts in SAME folder.
    """
    # --- 1. Infrastructure Setup ---
    print("\n[Setup] Starting isolated infrastructure...")

    # Redis
    redis = RedisContainer("redis:7-alpine")
    redis.start()
    redis_host = redis.get_container_host_ip()
    redis_port = redis.get_exposed_port(6379)
    redis_url = f"redis://{redis_host}:{redis_port}"

    # Postgres
    project_root = Path(__file__).parent.parent.parent
    init_sql_path = project_root / "scripts" / "db" / "init.sql"

    if "TESTCONTAINERS_RYUK_DISABLED" not in os.environ:
        os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"

    postgres = PostgresContainer(
        "timescale/timescaledb-ha:pg17",
        username="testuser",
        password="testpass",
        dbname="silvasonic_test",
    )
    postgres.with_volume_mapping(
        str(init_sql_path), "/docker-entrypoint-initdb.d/init.sql", mode="z"
    )
    postgres.start()

    pg_host = postgres.get_container_host_ip()
    pg_port = postgres.get_exposed_port(5432)
    postgres_url = f"postgresql+asyncpg://testuser:testpass@{pg_host}:{pg_port}/silvasonic_test"

    print(f"[Setup] Infrastructure Ready.\nRedis: {redis_url}\nDB: {postgres_url}")

    try:
        # Prepare DB
        engine = create_async_engine(postgres_url)
        async_session_local = async_sessionmaker(engine, expire_on_commit=False)

        # Seed Profile
        async with async_session_local() as session:
            profile = MicrophoneProfile(
                slug="generic_usb",
                name="Generic USB Mic",
                description="Default profile",
                match_pattern="usb:*",
                config={
                    "audio": {"sample_rate": 48000, "channels": 1, "format": "S16LE"},
                    "stream": {"segment_duration_s": 2},  # Short segments for testing
                },
                is_system=True,
            )
            session.add(profile)
            await session.commit()

        # Mock Settings & Paths
        with (
            patch("silvasonic.controller.main.settings") as settings_mock,
            patch("silvasonic.controller.orchestrator.settings", new=settings_mock),
            patch("silvasonic.core.redis.client.settings") as core_redis_settings_mock,
            patch("silvasonic.controller.main.AsyncSessionLocal", async_session_local),
        ):
            # Inject Config
            core_redis_settings_mock.redis_url = redis_url
            settings_mock.DATABASE_URL = postgres_url
            settings_mock.REDIS_HOST = redis_host

            # Paths
            settings_mock.HOST_DATA_DIR = str(tmp_path / "data")
            settings_mock.HOST_SOURCE_DIR = str(tmp_path / "source")
            os.makedirs(settings_mock.HOST_DATA_DIR, exist_ok=True)

            # Create profiles dir and file
            profiles_dir = Path(settings_mock.HOST_SOURCE_DIR) / "services/recorder/config/profiles"
            profiles_dir.mkdir(parents=True, exist_ok=True)

            profile_data = {
                "slug": "generic_usb",
                "name": "Generic USB Mic",
                "match_pattern": "usb:*",
                "audio": {"sample_rate": 48000, "channels": 1, "format": "S16LE"},
                "stream": {"segment_duration_s": 2},
                "is_system": True,
            }
            with open(profiles_dir / "generic_usb.yml", "w") as f:
                yaml.dump(profile_data, f)

            # Fix Permissions
            def recursive_chmod(path, mode):
                os.chmod(path, mode)
                for root, dirs, files in os.walk(path):
                    for d in dirs:
                        os.chmod(os.path.join(root, d), mode)
                    for f in files:
                        os.chmod(os.path.join(root, f), mode)

            try:
                recursive_chmod(tmp_path, 0o777)
            except Exception:
                pass

            # Mock Podman Rootless Socket if strictly needed
            uid = os.getuid()
            rootless_socket = f"/run/user/{uid}/podman/podman.sock"
            if os.path.exists(rootless_socket):
                settings_mock.PODMAN_SOCKET_URL = f"unix://{rootless_socket}"

            settings_mock.ICECAST_HOST = "localhost"
            settings_mock.PODMAN_NETWORK_NAME = "host"

            # Initialize Controller
            controller = ControllerService()
            controller.scanner = MagicMock()

            # Load Profiles
            async with async_session_local() as session:
                await controller.profiles.load_profiles(session)

            # --- Mocking Container Spawning (Critical for stability) ---
            # We use the real PodmanOrchestrator but we MOCK the internal _spawn_container to handle SELinux
            # AND we intercept spawn_recorder to inject test-specific env vars (lavfi)

            original_spawn = controller.podman.spawn_recorder

            def wrapped_spawn(*args, **kwargs):
                extra = {
                    "INPUT_FORMAT": "lavfi",
                    "INPUT_DEVICE_OVERRIDE": "sine=frequency=440:duration=600",
                    "MIC_PROFILE": "generic_usb",
                    "SILVASONIC_REDIS_PORT": str(redis_port),
                    "SILVASONIC_REDIS_HOST": redis_host,
                    "ICECAST_PASSWORD": "testing_password",
                }
                kwargs["extra_env"] = extra
                return original_spawn(*args, **kwargs)

            original_spawn_container = controller.podman._spawn_container

            def wrapped_spawn_container(*args, **kwargs):
                kwargs["security_opt"] = ["disable"]  # SELinux fix
                return original_spawn_container(*args, **kwargs)

            with (
                patch.object(controller.podman, "spawn_recorder", side_effect=wrapped_spawn),
                patch.object(
                    controller.podman, "_spawn_container", side_effect=wrapped_spawn_container
                ),
            ):
                # --- SCENARIO START ---

                # Define Device Identity
                device_serial = "PERSIST_TEST_01"
                short_serial = device_serial[-4:].lower()  # t_01
                # Expected folder name: generic_usb-<short_serial>
                # (Assuming logic in Controller uses Profile Slug + Short Serial)
                friendly_name = f"generic_usb-{short_serial}"

                device_mock = AudioDevice(
                    card_index=1,
                    id=f"usb-Persist_Mic_{device_serial}",
                    description="Persist Mic",
                    serial_number=device_serial,
                )

                # Expectation
                storage_path = (
                    Path(settings_mock.HOST_DATA_DIR)
                    / "recorder"
                    / friendly_name
                    / "recordings"
                    / "raw"
                )
                print(f"[Expectation] Storage Path: {storage_path}")

                # === PHASE 1: Connect ===
                print("\n[Phase 1] Connecting Device...")
                controller.scanner.find_recording_devices.return_value = [device_mock]

                await controller.reconcile()
                await asyncio.sleep(5)  # Wait for start

                # Verify Container Running
                containers = controller.podman.list_active_services()
                my_c = [c for c in containers if c.get("device_serial") == device_serial]
                assert len(my_c) == 1, "Phase 1: Recorder failed to start"
                print("[Check] Recorder Started (Phase 1).")

                # Verify File Creation (Wait for 1st file)
                files_ph1 = []
                for _ in range(5):
                    if storage_path.exists():
                        files_ph1 = list(storage_path.glob("*.wav"))
                        if files_ph1:
                            break
                    await asyncio.sleep(2)

                print(f"[Check] Phase 1 Files: {len(files_ph1)}")
                assert len(files_ph1) > 0, "Phase 1: No recordings generated."

                # === PHASE 2: Disconnect ===
                print("\n[Phase 2] Disconnecting Device...")
                controller.scanner.find_recording_devices.return_value = []  # Empty

                await controller.reconcile()
                await asyncio.sleep(3)  # Wait for stop

                # Verify Container Stopped
                containers = controller.podman.list_active_services()
                my_c = [c for c in containers if c.get("device_serial") == device_serial]
                assert len(my_c) == 0, "Phase 2: Recorder failed to stop"
                print("[Check] Recorder Stopped (Phase 2).")

                # === PHASE 3: Re-Connect (Identity Check) ===
                print("\n[Phase 3] Re-Connecting Device...")
                # FORCE RESET BACKOFF: We want to test persistence, not backoff here.
                # In real life, user would wait >10s.
                controller.backoff_state.clear()

                controller.scanner.find_recording_devices.return_value = [device_mock]

                await controller.reconcile()
                await asyncio.sleep(5)  # Wait for start

                # Verify Container Running AGAIN
                containers = controller.podman.list_active_services()
                my_c = [c for c in containers if c.get("device_serial") == device_serial]
                assert len(my_c) == 1, "Phase 3: Recorder failed to restart"
                print("[Check] Recorder Restarted (Phase 3).")

                # Verify New Files added to SAME directory
                # Wait for count increase
                files_ph3 = []
                for _ in range(6):
                    files_ph3 = list(storage_path.glob("*.wav"))
                    if len(files_ph3) > len(files_ph1):
                        break
                    await asyncio.sleep(2)

                print(f"[Check] Phase 3 Files: {len(files_ph3)} (Prev: {len(files_ph1)})")
                assert len(files_ph3) > len(files_ph1), (
                    "Phase 3: No new files generated in original directory!"
                )

                # Identity Check: Ensure NO duplicate directories
                recorder_root = Path(settings_mock.HOST_DATA_DIR) / "recorder"
                subdirs = [d.name for d in recorder_root.iterdir() if d.is_dir()]
                print(f"[Identity Check] Found Directories: {subdirs}")

                # Should only see 'generic_usb-t_01'
                assert len(subdirs) == 1, (
                    f"Found multiple recorder directories! Identity leakage? {subdirs}"
                )
                assert subdirs[0] == friendly_name, (
                    f"Directory name mismatch! Expected {friendly_name}, got {subdirs[0]}"
                )

                print("\nSUCCESS: Identity Persistence Verified. Same storage path reused.")

    finally:
        # Cleanup
        try:
            import podman

            uid = os.getuid()
            uri = f"unix:///run/user/{uid}/podman/podman.sock"
            p = podman.PodmanClient(base_url=uri)
            for c in p.containers.list():
                if "silvasonic-recorder" in c.name:
                    c.stop()
                    c.remove()
        except Exception:
            pass

        try:
            redis.stop()
        except Exception:
            pass
        try:
            postgres.stop()
        except Exception:
            pass
