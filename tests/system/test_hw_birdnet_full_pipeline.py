"""Hardware System Test for BirdNET Pipeline.

Tests the actual acoustic end-to-end pipeline:
- Starts DB and Redis.
- Start Recorder container without mock mode.
- Uses `ffplay` to emit sound from the host.
- The USB microphone records the sound.
- Starts Processor container.
- Starts BirdNET container.
- Mounts recordings_root and birdnet_workspace appropriately.
- Waits for BirdNET detections and clip generation.

NOTE: This requires the host machine's output sound to be unmuted and a real
USB microphone to be plugged in.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import MountSpec, RestartPolicy, Tier2ServiceSpec

from ._processor_helpers import (
    BIRDNET_IMAGE,
    PROCESSOR_IMAGE,
    make_processor_env,
    podman_logs,
    podman_run,
    podman_stop_rm,
    psql_query,
    require_birdnet_image,
    require_processor_image,
    seed_processor_config,
    seed_test_devices,
    wait_for_db_rows,
    wait_for_detection,
    wait_for_wavs,
)


def has_ffplay() -> bool:
    """Check if ffplay is installed on the host."""
    try:
        result = subprocess.run(["ffplay", "-version"], capture_output=True, timeout=2)
        return result.returncode == 0
    except OSError:
        return False


@pytest.mark.system_hw_manual
@pytest.mark.timeout(120)
class TestHardwareBirdNETFullPipeline:
    def test_room_playback_to_microphone_to_birdnet_creates_detection_clip(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        container_manager: ContainerManager,
        primary_device: Any,
    ) -> None:
        """Physical data pipeline verification using live playback."""
        if not has_ffplay():
            pytest.skip("ffplay is not installed on the dev host")

        require_processor_image()
        require_birdnet_image()

        target_alsa_device = primary_device.alsa_device

        from .conftest import RECORDER_IMAGE

        db_name, run_id = system_db
        _, _, redis_name = system_redis

        fixture_path = Path.cwd() / "tests" / "fixtures" / "audio"
        fixture_wav = "XC521936 - European Robin - Erithacus rubecula.wav"
        fixture_full_path = fixture_path / fixture_wav
        assert fixture_full_path.exists(), f"Fixture missing: {fixture_wav}"

        # -----------------------------------------------------
        # Seed configurations
        # -----------------------------------------------------
        seed_processor_config(db_name)

        birdnet_cfg = {
            "processing_order": "newest_first",
            "overlap": 0.0,
            # Because it's played out loud into a room, the match score drops
            "confidence_threshold": 0.0,
        }
        cfg_json = json.dumps(birdnet_cfg)
        psql_query(
            db_name,
            f"""INSERT INTO system_config (key, value)
               VALUES ('birdnet', '{cfg_json}'::jsonb)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        )

        test_device = "mic-aaa"
        # Overwrite device seed specifically with correct ID to test physical capture
        seed_test_devices(db_name, [test_device])

        # -----------------------------------------------------
        # Prepare Workspaces
        # -----------------------------------------------------
        recordings_root = tmp_path / "recordings"
        recorder_workspace = recordings_root / test_device
        recorder_workspace.mkdir(parents=True, exist_ok=True)
        # Create .buffer to avoid PermissionErrror in recorder container
        (recorder_workspace / ".buffer" / "processed").mkdir(parents=True, exist_ok=True)
        (recorder_workspace / "data" / "processed").mkdir(parents=True, exist_ok=True)
        (recorder_workspace / ".keep").touch()

        birdnet_workspace = tmp_path / "birdnet_workspace"
        birdnet_workspace.mkdir(parents=True, exist_ok=True)
        (birdnet_workspace / "clips").mkdir(parents=True, exist_ok=True)

        recorder_name = f"silvasonic-recorder-{run_id}"
        processor_name = f"silvasonic-processor-{run_id}"
        birdnet_name = f"silvasonic-birdnet-{run_id}"
        mgr = container_manager
        ffplay_proc = None

        try:
            # 1. Start Recorder using the Container Manager to handle device propagation safely
            spec = Tier2ServiceSpec(
                name=recorder_name,
                image=RECORDER_IMAGE,
                environment={
                    "SILVASONIC_INSTANCE_ID": test_device,
                    "SILVASONIC_RECORDER_DEVICE": target_alsa_device,
                    "SILVASONIC_REDIS_URL": f"redis://{redis_name}:6379/0",
                    "SILVASONIC_RECORDER_WORKSPACE": "/app/workspace",
                    "SILVASONIC_RECORDER_PROFILE_SLUG": "test_profile",
                    "SILVASONIC_RECORDER_CONFIG_JSON": (
                        '{"stream": {"segment_duration_s": 3, '
                        '"raw_enabled": false, "processed_enabled": true}, '
                        '"processing": {"gain_db": 0.0}, '
                        '"audio": {"sample_rate": 48000, "channels": 1, "format": "S16LE"}}'
                    ),
                },
                restart_policy=RestartPolicy(name="no", max_retry_count=0),
                memory_limit="128m",
                cpu_limit=0.5,
                oom_score_adj=-999,
                mounts=[
                    MountSpec(
                        source=str(recorder_workspace),
                        target="/app/workspace",
                        read_only=False,
                    )
                ],
                devices=["/dev/snd"],
                network=system_network,
            )
            cid = mgr.start(spec)
            assert cid is not None, "Failed to start recorder container"

            # 2. Play the sound physically out loud using ffplay
            # Note: Unmuting is a manual precondition.
            ffplay_proc = subprocess.Popen(
                [
                    "ffplay",
                    "-nodisp",
                    "-autoexit",
                    "-v",
                    "quiet",
                    "-loop",
                    "5",
                    str(fixture_full_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Wait to accumulate some WAVs generated from physical capture (6-9 seconds)
            wait_for_wavs(recorder_workspace / "data" / "processed", min_count=2, timeout=20)

            # Stop the Recorder & playback
            mgr.stop(recorder_name, timeout=5)
            if ffplay_proc:
                ffplay_proc.terminate()
                ffplay_proc.wait()
                ffplay_proc = None

            # 3. Start Processor
            proc_env = make_processor_env()
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=proc_env,
                volumes=[f"{recordings_root.resolve()}:/data/recorder:z"],
                network=system_network,
            )

            # Wait for Processor to Index the WAVs
            wait_for_db_rows(db_name, "SELECT COUNT(*) FROM recordings", min_count=2, timeout=30)

            # 4. Start BirdNET
            podman_run(
                birdnet_name,
                BIRDNET_IMAGE,
                env={
                    "SILVASONIC_DB_HOST": "database",
                    "SILVASONIC_DB_PORT": "5432",
                    "POSTGRES_USER": "silvasonic",
                    "POSTGRES_PASSWORD": "silvasonic",
                    "POSTGRES_DB": "silvasonic",
                    "SILVASONIC_REDIS_URL": f"redis://{redis_name}:6379/0",
                    "SILVASONIC_RECORDINGS_DIR": "/data/recorder",
                    "SILVASONIC_WORKSPACE_DIR": "/data/birdnet",
                },
                volumes=[
                    f"{birdnet_workspace.resolve()}:/data/birdnet:z",
                    f"{recordings_root.resolve()}:/data/recorder:ro,z",
                ],
                network=system_network,
            )

            # -----------------------------------------------------
            # Assertions
            # -----------------------------------------------------
            # 5. Wait for BirdNET detection!
            detection = wait_for_detection(db_name, prefix_taxon="", timeout=40)

            assert detection["clip_path"].startswith("clips/")

            # 6. Verify physical Clip existence
            clip_file = birdnet_workspace / detection["clip_path"]
            assert clip_file.exists(), f"Physical clip missing at {clip_file}"
            assert clip_file.stat().st_size > 1000, "Clip is unusually small/empty"

        except BaseException as exc:
            print(f"\\n--- {recorder_name} LOGS ---")
            print(podman_logs(recorder_name))
            print(f"\\n--- {processor_name} LOGS ---")
            print(podman_logs(processor_name))
            print(f"\\n--- {birdnet_name} LOGS ---")
            print(podman_logs(birdnet_name))
            raise exc

        finally:
            podman_stop_rm(recorder_name)
            podman_stop_rm(processor_name)
            podman_stop_rm(birdnet_name)
            if ffplay_proc:
                ffplay_proc.terminate()
