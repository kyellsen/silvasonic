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
async def test_recorder_survival_without_infrastructure(tmp_path):
    """Resiliency Test:
    1. Start Infrastructure (DB, Redis)
    2. Start Recorder (via Controller)
    3. KILL Infrastructure (DB, Redis)
    4. Verify Recorder keeps running and recording
    """
    # --- 1. Infrastructure Setup (Manual Control) ---
    print("\n[Setup] Starting isolated infrastructure...")

    # Redis
    redis = RedisContainer("redis:7-alpine")
    redis.start()
    redis_host = redis.get_container_host_ip()
    redis_port = redis.get_exposed_port(6379)
    redis_url = f"redis://{redis_host}:{redis_port}"

    # Postgres
    # Resolve init.sql path relative to this test file
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
        # --- 2. Controller & Recorder Start ---

        # Prepare DB
        engine = create_async_engine(postgres_url)
        async_session_local = async_sessionmaker(engine, expire_on_commit=False)

        # Seed Profile in DB (for Controller)
        # Note: DB model 'config' column stores the component configs (audio, stream, etc)
        async with async_session_local() as session:
            profile = MicrophoneProfile(
                slug="generic_usb",
                name="Generic USB Mic",
                description="Default profile",
                match_pattern="usb:*",
                config={
                    "audio": {"sample_rate": 48000, "channels": 1, "format": "S16LE"},
                    "stream": {"segment_duration_s": 2},
                },
                is_system=True,
            )
            session.add(profile)
            await session.commit()

        # Mock Settings
        with (
            patch("silvasonic.controller.main.settings") as settings_mock,
            patch("silvasonic.controller.orchestrator.settings", new=settings_mock),
            patch("silvasonic.core.redis.client.settings") as core_redis_settings_mock,
            patch("silvasonic.controller.main.AsyncSessionLocal", async_session_local),
        ):
            # Inject Infrastructure URLs
            core_redis_settings_mock.redis_url = redis_url
            settings_mock.DATABASE_URL = postgres_url
            settings_mock.REDIS_HOST = redis_host

            # Paths
            settings_mock.HOST_DATA_DIR = str(tmp_path / "data")
            settings_mock.HOST_SOURCE_DIR = str(tmp_path / "source")
            os.makedirs(settings_mock.HOST_DATA_DIR, exist_ok=True)

            # Create profiles dir to avoid FileNotFoundError in load_profiles if logic checks it
            profiles_dir = Path(settings_mock.HOST_SOURCE_DIR) / "services/recorder/config/profiles"
            profiles_dir.mkdir(parents=True, exist_ok=True)

            # Create the missing profile YAML file (Required by Recorder Container)
            # Structure must match MicrophoneProfile Pydantic model (flattened structure + required fields)
            profile_data = {
                "slug": "generic_usb",
                "name": "Generic USB Mic",
                "description": "Default profile",
                "match_pattern": "usb:*",
                "audio": {"sample_rate": 48000, "channels": 1, "format": "S16LE"},
                "stream": {"segment_duration_s": 2},
                "is_system": True,
            }
            with open(profiles_dir / "generic_usb.yml", "w") as f:
                yaml.dump(profile_data, f)

            # Pre-create LOGS dir with correct permissions (because spawn_recorder creates it too late)
            device_serial = "RESILIENCY_TEST_01"
            short_serial = device_serial[-4:].lower()  # t_01
            friendly_name = f"generic_usb-{short_serial}"
            logs_dir = Path(settings_mock.HOST_DATA_DIR) / "recorder" / friendly_name / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            # Fix Permissions: Recursively chmod 777
            # This ensures the container (running as unknown UID) can read/write mapped volumes
            def recursive_chmod(path, mode):
                os.chmod(path, mode)
                for root, dirs, files in os.walk(path):
                    for d in dirs:
                        os.chmod(os.path.join(root, d), mode)
                    for f in files:
                        os.chmod(os.path.join(root, f), mode)

            try:
                # Apply to everything in tmp_path including logs/profiles
                recursive_chmod(tmp_path, 0o777)
            except Exception as e:
                print(f"Warning: Failed to chmod temp dir: {e}")

            # Update DOCKER_HOST if needed for rootless
            uid = os.getuid()
            rootless_socket = f"/run/user/{uid}/podman/podman.sock"
            if os.path.exists(rootless_socket):
                settings_mock.PODMAN_SOCKET_URL = f"unix://{rootless_socket}"

            settings_mock.ICECAST_HOST = "localhost"
            settings_mock.PODMAN_NETWORK_NAME = "host"

            # Init Controller
            controller = ControllerService()
            controller.scanner = MagicMock()  # Mock Hardware

            # Load Profiles
            async with async_session_local() as session:
                await controller.profiles.load_profiles(session)

            # Fake Device
            fake_device = AudioDevice(
                card_index=1,
                id=f"usb-Resilient_Mic_{device_serial}",
                description="Resilient Mic",
                serial_number=device_serial,
            )
            controller.scanner.find_recording_devices.return_value = [fake_device]

            # Intercept Spawn to inject Lavfi (Env Vars)
            original_spawn = controller.podman.spawn_recorder

            def wrapped_spawn(*args, **kwargs):
                extra = {
                    "INPUT_FORMAT": "lavfi",
                    "INPUT_DEVICE_OVERRIDE": "sine=frequency=440:duration=600",  # Long duration for test
                    "MIC_PROFILE": "generic_usb",
                    # Fix: Inject the actual mapped port from Testcontainers
                    "SILVASONIC_REDIS_PORT": str(redis_port),
                    "SILVASONIC_REDIS_HOST": redis_host,
                    "ICECAST_PASSWORD": "testing_password",
                }
                kwargs["extra_env"] = extra
                return original_spawn(*args, **kwargs)

            # Intercept _spawn_container to inject Security Opts (SELinux fix)
            original_spawn_container = controller.podman._spawn_container

            def wrapped_spawn_container(*args, **kwargs):
                # Disable SELinux labeling to avoid PermissionDenied on bind mounts
                # Trying 'disable' keyword directly based on error message
                kwargs["security_opt"] = ["disable"]
                return original_spawn_container(*args, **kwargs)

            with (
                patch.object(controller.podman, "spawn_recorder", side_effect=wrapped_spawn),
                patch.object(
                    controller.podman, "_spawn_container", side_effect=wrapped_spawn_container
                ),
            ):
                print("[Action] Spawning Recorder...")
                await controller.reconcile()

                # Verify Running
                await asyncio.sleep(5)
                # Helper Variables
                container_name = f"silvasonic-recorder-{friendly_name}"

                containers = controller.podman.list_active_services()
                my_c = [c for c in containers if c.get("device_serial") == device_serial]

                if len(my_c) != 1:
                    # Debug: Print logs
                    try:
                        # Try to get logs even if stopped
                        import podman

                        uid = os.getuid()
                        uri = f"unix:///run/user/{uid}/podman/podman.sock"
                        client_debug = podman.PodmanClient(base_url=uri)
                        try:
                            c_debug = client_debug.containers.get(container_name)
                            print(f"DEBUG: Container State: {c_debug.status}")

                            logs = c_debug.logs()
                            if hasattr(logs, "__iter__") and not isinstance(logs, (str, bytes)):
                                full_log = b"".join(
                                    [chunk for chunk in logs]
                                )  # Usually yields bytes
                                print(
                                    f"DEBUG: Container Logs:\n{full_log.decode('utf-8', errors='replace')}"
                                )
                            else:
                                print(
                                    f"DEBUG: Container Logs:\n{logs.decode('utf-8', errors='replace')}"
                                )
                        except Exception as e_inner:
                            print(f"DEBUG: Container fetch failed: {e_inner}")

                    except Exception as e:
                        print(f"DEBUG: Could not fetch logs: {e}")

                assert len(my_c) == 1, "Recorder failed to start"
                print("[Check] Recorder Started.")

                # Check initial files
                rec_path = (
                    Path(settings_mock.HOST_DATA_DIR)
                    / "recorder"
                    / friendly_name
                    / "recordings"
                    / "raw"
                )

                # Ideally wait until 1 file exists
                files_initial = []
                for _ in range(5):
                    files_initial = list(rec_path.glob("*.wav"))
                    if files_initial:
                        break
                    print("Waiting for first file...")
                    await asyncio.sleep(2)

                print(f"[Check] Initial Files: {len(files_initial)}")
                assert len(files_initial) > 0, "No files generated initially"

                # --- 3. DISASTER SIMULATION ---
                print("\n[DISASTER] KILLING REDIS AND POSTGRES...")
                redis.stop()
                postgres.stop()
                print("[DISASTER] Infrastructure Destroyed.")

                # Wait for chaos (Recorder uses 5s heartbeat, 2s segments)
                wait_time = 10
                print(f"Waiting {wait_time}s for recorder to survive...")
                await asyncio.sleep(wait_time)

                # --- 4. VERIFICATION ---

                try:
                    import podman

                    uid = os.getuid()
                    uri = f"unix:///run/user/{uid}/podman/podman.sock"
                    client_check = podman.PodmanClient(base_url=uri)
                    c_after = client_check.containers.get(container_name)
                    print(f"[Status] Container Status after Disaster: {c_after.status}")
                    assert c_after.status == "running", (
                        "Recorder container died after infrastructure collapse!"
                    )
                except Exception as e:
                    pytest.fail(f"Could not inspect container: {e}")

                # Check 2: New files created?
                files_after = list(rec_path.glob("*.wav"))
                print(f"[Check] Files After Disaster: {len(files_after)}")

                # Start: 1 file. Wait 10s (segment=2s). Should have ~5 more files.
                # Allow some slack
                # Original wait 10s / 2s segment = +5 files.
                # Just checking improvement
                assert len(files_after) > len(files_initial), "Recorder stopped producing files!"
                print("SUCCESS: Recorder kept writing files to disk.")

    finally:
        # Cleanup
        print("\n[Cleanup] Teardown...")
        try:
            # Re-init podman client just in case
            import podman

            uid = os.getuid()
            uri = f"unix:///run/user/{uid}/podman/podman.sock"
            p_client = podman.PodmanClient(base_url=uri)

            # Find and kill
            for c in p_client.containers.list():
                if "silvasonic-recorder" in c.name and "generic_usb" in c.name:
                    print(f"Stopping {c.name}")
                    c.stop()
                    c.remove()
        except Exception as e:
            print(f"Cleanup non-critical error: {e}")

        try:
            redis.stop()
        except Exception:
            pass
        try:
            postgres.stop()
        except Exception:
            pass
