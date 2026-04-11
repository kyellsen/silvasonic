"""Automated System Test for BirdNET Pipeline.

Tests the deterministic full internal pipeline without hardware triggers:
- Starts DB and Redis.
- Start Recorder container in mock mode (using a specific Fixture).
- Starts Processor container.
- Starts BirdNET container.
- Mounts recordings_root and birdnet_workspace appropriately.
- Waits for BirdNET detections and clip generation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ._processor_helpers import (
    BIRDNET_IMAGE,
    PROCESSOR_IMAGE,
    make_processor_env,
    podman_run,
    podman_stop_rm,
    psql_query,
    require_birdnet_image,
    require_processor_image,
    seed_processor_config,
    wait_for_db_rows,
    wait_for_detection,
    wait_for_wavs,
)


@pytest.mark.system
@pytest.mark.timeout(90)
class TestBirdNETFullPipeline:
    def test_mock_recorder_to_processor_to_birdnet_creates_detection_clip(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
    ) -> None:
        """Full data pipeline verification using a mock audio file."""
        from .conftest import RECORDER_IMAGE  # Use globally available fixture constant

        require_processor_image()
        require_birdnet_image()

        db_name, run_id = system_db
        _, _, redis_name = system_redis

        # The specific fixture to loop in the recorder
        fixture_path = Path.cwd() / "tests" / "fixtures" / "audio"
        fixture_wav = "XC521936 - European Robin - Erithacus rubecula.wav"
        assert (fixture_path / fixture_wav).exists(), f"Fixture missing: {fixture_wav}"

        # -----------------------------------------------------
        # Seed configurations
        # -----------------------------------------------------
        seed_processor_config(db_name)

        # Seed BirdNET config into system_config
        birdnet_cfg = {
            "processing_order": "newest_first",
            "overlap": 0.0,
            "confidence_threshold": 0.0,  # Zero guarantees pipeline throughput
        }
        cfg_json = json.dumps(birdnet_cfg)
        psql_query(
            db_name,
            f"""INSERT INTO system_config (key, value)
               VALUES ('birdnet', '{cfg_json}'::jsonb)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        )

        test_device = "mic-aaa"

        # -----------------------------------------------------
        # Prepare Workspaces
        # -----------------------------------------------------
        # recordings_root is bound to /data/recorder
        recordings_root = tmp_path / "recordings"
        recorder_workspace = recordings_root / test_device
        recorder_workspace.mkdir(parents=True, exist_ok=True)
        # Create .buffer to avoid PermissionErrror in recorder container
        (recorder_workspace / ".buffer" / "processed").mkdir(parents=True, exist_ok=True)
        (recorder_workspace / "data" / "processed").mkdir(parents=True, exist_ok=True)

        # We need a dummy object so globbing paths works
        (recorder_workspace / ".keep").touch()

        birdnet_workspace = tmp_path / "birdnet_workspace"
        birdnet_workspace.mkdir(parents=True, exist_ok=True)
        (birdnet_workspace / "clips").mkdir(parents=True, exist_ok=True)

        # -----------------------------------------------------
        # Container Setup
        # -----------------------------------------------------
        recorder_name = f"silvasonic-recorder-{run_id}"
        processor_name = f"silvasonic-processor-{run_id}"
        birdnet_name = f"silvasonic-birdnet-{run_id}"

        try:
            # 1. Start Recorder (Mock Mode with specific file)
            # The test-fixtures mount allows the mock file to be read by the container.
            # SILVASONIC_RECORDER_MOCK_FILE points to the container-side path.
            podman_run(
                recorder_name,
                RECORDER_IMAGE,
                env={
                    "SILVASONIC_INSTANCE_ID": test_device,
                    "SILVASONIC_RECORDER_DEVICE": "hw:99,0",
                    "SILVASONIC_RECORDER_MOCK_SOURCE": "true",
                    "SILVASONIC_RECORDER_MOCK_FILE": f"/app/test-fixtures/{fixture_wav}",
                    "SILVASONIC_REDIS_URL": f"redis://{redis_name}:6379/0",
                    "SILVASONIC_RECORDER_WORKSPACE": "/app/workspace",
                    "SILVASONIC_RECORDER_PROFILE_SLUG": "test_profile",
                    # Ensure it actually builds a JSON config for processed segments
                    "SILVASONIC_RECORDER_CONFIG_JSON": (
                        '{"stream": {"segment_duration_s": 5, '
                        '"raw_enabled": false, "processed_enabled": true}, '
                        '"processing": {"gain_db": 0.0}, '
                        '"audio": {"sample_rate": 48000, "channels": 1, "format": "S16LE"}}'
                    ),
                },
                volumes=[
                    f"{recorder_workspace.resolve()}:/app/workspace:z",
                    f"{fixture_path.resolve()}:/app/test-fixtures:z,ro",
                ],
                network=system_network,
            )

            # 2. Wait for Recorder to drop a few WAV segments
            # The Processor will automatically pick this up. Waiting for 4 chunks = 20 seconds.
            wait_for_wavs(recorder_workspace / "data" / "processed", min_count=4, timeout=40)

            # Stop the Recorder so we don't spam the DB with endless loops for a simple test
            podman_stop_rm(recorder_name)

            # 3. Start Processor
            proc_env = make_processor_env()
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=proc_env,
                volumes=[
                    f"{recordings_root.resolve()}:/data/recorder:z",
                ],
                network=system_network,
            )

            # Wait for Processor to Index the WAVs
            wait_for_db_rows(db_name, "SELECT COUNT(*) FROM recordings", min_count=4, timeout=30)

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
                    # Point to full recordings tree and private workspace
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
            # Since confidence is 0.0, we just wait for ANY detection to prove the pipeline works
            detection = wait_for_detection(db_name, prefix_taxon="", timeout=40)

            assert detection["clip_path"].startswith("clips/")

            # 6. Verify physical Clip existence
            clip_file = birdnet_workspace / detection["clip_path"]
            assert clip_file.exists(), f"Physical clip missing at {clip_file}"
            assert clip_file.stat().st_size > 1000, "Clip is unusually small/empty"

        except BaseException as exc:
            # Dump database rows to see what BirdNET actually found
            print("\n--- BIRDNET DETECTIONS ---")
            import subprocess

            res = subprocess.run(
                [
                    "podman",
                    "exec",
                    db_name,
                    "psql",
                    "-U",
                    "silvasonic",
                    "-d",
                    "silvasonic",
                    "-c",
                    "SELECT id, label, confidence FROM detections "
                    "ORDER BY confidence DESC LIMIT 20;",
                ],
                capture_output=True,
                text=True,
            )
            print(res.stdout)
            print(res.stderr)
            raise exc

        finally:
            podman_stop_rm(recorder_name)
            podman_stop_rm(processor_name)
            podman_stop_rm(birdnet_name)
