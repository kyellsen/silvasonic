"""System tests: Processor Lifecycle — full Recorder → Processor pipeline.

Tests the complete data flow from Recorder (mock audio source) through the
Processor Indexer into the PostgreSQL ``recordings`` table.

Requires:
- Running Podman socket on the host.
- Built images: ``silvasonic_recorder:latest``, ``silvasonic_processor:latest``,
  ``silvasonic_database:latest``.
- No production stack running (``just stop`` first).

Usage::

    just test-system

Architecture:
- PostgreSQL (``silvasonic_database`` image) on an isolated test network with alias ``database``.
- Redis on the same isolated network with alias ``redis``.
- Recorder container (mock source) writes WAV segments to a shared workspace.
- Processor container indexes those WAV files into the ``recordings`` table.
- Assertions use ``podman exec ... psql`` for DB queries (no extra driver dep).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from redis import Redis

from ._processor_helpers import (
    PROCESSOR_IMAGE,
    make_processor_env,
    make_recorder_env,
    podman_logs,
    podman_run,
    podman_stop_rm,
    psql_query,
    require_processor_image,
)
from .conftest import (
    PODMAN_SOCKET,
    SOCKET_AVAILABLE,
    require_recorder_image,
)

pytestmark = [
    pytest.mark.system,
    pytest.mark.skipif(
        not SOCKET_AVAILABLE,
        reason=f"Podman socket not found at {PODMAN_SOCKET}",
    ),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProcessorLifecycle:
    """Verify Processor integration with Recorder in system-level tests.

    Each test spins up ephemeral DB + Redis + Recorder + Processor containers
    on an isolated Podman network and validates end-to-end data flow.
    """

    @pytest.mark.timeout(120)
    def test_recorder_to_processor_pipeline(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """Recorder (mock source) → WAV → Processor Indexer → recordings in DB.

        This is the critical pipeline test that validates the full data flow
        from audio capture to database registration.
        """
        require_recorder_image()
        require_processor_image()

        db_container, _ = system_db

        # Workspace layout mirrors production:
        # {recordings_root}/{device_id}/data/processed/*.wav
        recordings_root = tmp_path / "recorder"
        device_workspace = recordings_root / "test-device"
        recordings_root.mkdir(parents=True, exist_ok=True)
        device_workspace.mkdir(parents=True, exist_ok=True)
        recordings_root.chmod(0o777)
        device_workspace.chmod(0o777)

        recorder_name = f"silvasonic-recorder-systest-{run_id}"
        processor_name = f"silvasonic-processor-systest-{run_id}"

        try:
            # Start Recorder with mock source — writes to {device_workspace}
            podman_run(
                recorder_name,
                "localhost/silvasonic_recorder:latest",
                env=make_recorder_env(),
                volumes=[f"{device_workspace}:/app/workspace:z"],
                network=system_network,
            )

            # Wait for Recorder to produce at least 2 promoted segments
            time.sleep(25)

            # Verify WAV files exist before starting Processor
            data_dir = device_workspace / "data" / "processed"
            wav_files = list(data_dir.glob("*.wav")) if data_dir.exists() else []
            if not wav_files:
                print(f"\n--- RECORDER LOGS ---\n{podman_logs(recorder_name)}")
            assert len(wav_files) >= 1, (
                f"Recorder did not produce WAV files in {device_workspace}. "
                f"Contents: {list(device_workspace.rglob('*'))}"
            )

            # Start Processor — recordings_root contains device subdirectories
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{recordings_root}:/data/recorder:z"],
                network=system_network,
            )

            # Wait for Processor to index the files
            time.sleep(15)

            # Query DB via psql inside DB container
            count_str = psql_query(db_container, "SELECT COUNT(*) FROM recordings")
            count = int(count_str) if count_str else 0

            if count == 0:
                print(f"\n--- PROCESSOR LOGS ---\n{podman_logs(processor_name)}")
                print(f"\n--- RECORDER LOGS ---\n{podman_logs(recorder_name)}")

            assert count >= 1, (
                f"Processor did not index any recordings. "
                f"WAV files on disk: {len(wav_files)}. "
                f"Check Processor logs: podman logs {processor_name}"
            )

            # Verify recording metadata
            rows_str = psql_query(
                db_container,
                "SELECT sensor_id, file_processed, duration, sample_rate FROM recordings",
            )
            for line in rows_str.splitlines():
                parts = line.split("|")
                assert len(parts) >= 4, f"Unexpected row format: {line}"
                sensor_id, file_proc = parts[0], parts[1]
                duration, sample_rate = float(parts[2]), int(parts[3])
                assert sensor_id, "sensor_id must not be empty"
                assert file_proc, "file_processed must not be empty"
                assert duration > 0, f"duration must be > 0, got {duration}"
                assert sample_rate > 0, f"sample_rate must be > 0, got {sample_rate}"

            print(
                f"\n  ✅ Pipeline verified: {count} recording(s) indexed from "
                f"{len(wav_files)} WAV file(s)"
            )
        finally:
            podman_stop_rm(processor_name)
            podman_stop_rm(recorder_name)

    @pytest.mark.timeout(60)
    def test_heartbeat_has_processor_metrics(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """Processor heartbeat in Redis contains indexer and janitor metrics."""
        require_processor_image()

        redis_host, redis_port, _redis_container = system_redis

        workspace = tmp_path / "recorder"
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o777)

        processor_name = f"silvasonic-processor-hb-{run_id}"

        try:
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{workspace}:/data/recorder:z"],
                network=system_network,
            )

            # Wait for Processor to publish at least one heartbeat
            time.sleep(12)

            # Check Redis for heartbeat
            r = Redis(host=redis_host, port=redis_port, decode_responses=True)
            heartbeat_raw: str | None = None

            for _ in range(20):
                keys: list[str] = list(r.keys("silvasonic:status:*"))  # type: ignore[arg-type]
                for key in keys:
                    val = r.get(key)
                    if val is not None:
                        try:
                            data = json.loads(str(val))
                            if data.get("service") == "processor":
                                heartbeat_raw = str(val)
                                break
                        except (json.JSONDecodeError, TypeError):
                            continue
                if heartbeat_raw:
                    break
                time.sleep(1)

            r.close()

            if heartbeat_raw is None:
                print(f"\n--- PROCESSOR LOGS ---\n{podman_logs(processor_name)}")

            assert heartbeat_raw is not None, "No processor heartbeat found in Redis after 20s"

            payload = json.loads(heartbeat_raw)
            if payload.get("health", {}).get("status") != "ok":
                print(f"Health was not OK! Payload: {json.dumps(payload, indent=2)}")
                print(f"\n--- PROCESSOR LOGS ---\n{podman_logs(processor_name)}")
            assert payload["service"] == "processor"
            assert "health" in payload
            assert payload["health"]["status"] == "ok"

            meta = payload.get("meta", {})
            assert "indexer" in meta, f"Missing 'indexer' in heartbeat meta: {meta.keys()}"
            assert "janitor" in meta, f"Missing 'janitor' in heartbeat meta: {meta.keys()}"

            indexer_meta = meta["indexer"]
            assert "total_indexed" in indexer_meta
            assert "last_indexed_at" in indexer_meta

            janitor_meta = meta["janitor"]
            assert "disk_usage_percent" in janitor_meta
            assert "current_mode" in janitor_meta
            assert "files_deleted_total" in janitor_meta

            print(
                f"\n  ✅ Heartbeat verified: "
                f"indexed={indexer_meta['total_indexed']}, "
                f"disk={janitor_meta['disk_usage_percent']}%, "
                f"mode={janitor_meta['current_mode']}"
            )
        finally:
            podman_stop_rm(processor_name)

    @pytest.mark.timeout(60)
    def test_upload_worker_starts_with_processor(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """Upload worker initializes successfully when Processor starts."""
        require_processor_image()

        workspace = tmp_path / "recorder"
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o777)

        processor_name = f"silvasonic-processor-uw-start-{run_id}"

        try:
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{workspace}:/data/recorder:z"],
                network=system_network,
            )

            # Wait for Processor to publish logs
            time.sleep(12)

            logs = podman_logs(processor_name)

            assert "upload_worker.started" in logs, (
                f"Missing upload_worker.started in logs:\n{logs}"
            )

            print("\n  ✅ Upload worker start verified.")
        finally:
            podman_stop_rm(processor_name)

    @pytest.mark.timeout(60)
    def test_upload_disabled_no_rclone(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """Disabled CloudSyncSettings skips upload worker processing safely."""
        require_processor_image()

        workspace = tmp_path / "recorder"
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o777)

        processor_name = f"silvasonic-processor-uw-dis-{run_id}"

        try:
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{workspace}:/data/recorder:z"],
                network=system_network,
            )

            time.sleep(12)

            logs = podman_logs(processor_name)

            assert "rclone" not in logs.lower() and "upload_worker.started" in logs, (
                f"Upload worker should not spawn rclone when disabled:\n{logs}"
            )

            print("\n  ✅ Upload worker handles disabled state.")
        finally:
            podman_stop_rm(processor_name)

    @pytest.mark.timeout(120)
    def test_processor_restart_idempotent(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """Stop and restart Processor → no duplicate recordings rows."""
        require_recorder_image()
        require_processor_image()

        db_container, _ = system_db

        recordings_root = tmp_path / "recorder"
        device_workspace = recordings_root / "test-device"
        recordings_root.mkdir(parents=True, exist_ok=True)
        device_workspace.mkdir(parents=True, exist_ok=True)
        recordings_root.chmod(0o777)
        device_workspace.chmod(0o777)

        recorder_name = f"silvasonic-recorder-restart-{run_id}"
        processor_name = f"silvasonic-processor-restart-{run_id}"

        processor_env = make_processor_env()

        try:
            # Start Recorder
            podman_run(
                recorder_name,
                "localhost/silvasonic_recorder:latest",
                env=make_recorder_env(),
                volumes=[f"{device_workspace}:/app/workspace:z"],
                network=system_network,
            )

            time.sleep(20)

            # Start Processor (first run)
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=processor_env,
                volumes=[f"{recordings_root}:/data/recorder:z"],
                network=system_network,
            )
            time.sleep(12)

            # Count recordings after first run
            count_str = psql_query(db_container, "SELECT COUNT(*) FROM recordings")
            count_first = int(count_str) if count_str else 0

            assert count_first >= 1, "First Processor run should index at least 1 recording"

            # Stop Processor
            podman_stop_rm(processor_name)
            time.sleep(2)

            # Restart Processor (second run)
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=processor_env,
                volumes=[f"{recordings_root}:/data/recorder:z"],
                network=system_network,
            )
            time.sleep(12)

            # Count recordings after restart
            count_str = psql_query(db_container, "SELECT COUNT(*) FROM recordings")
            count_second = int(count_str) if count_str else 0

            # Check for duplicates: each file_processed must be unique
            dup_str = psql_query(
                db_container,
                """SELECT file_processed, COUNT(*) as cnt
                   FROM recordings
                   GROUP BY file_processed
                   HAVING COUNT(*) > 1""",
            )
            duplicate_rows = [line for line in dup_str.splitlines() if line.strip()]

            assert len(duplicate_rows) == 0, (
                f"Duplicate recordings found after restart: {duplicate_rows}"
            )
            assert count_second >= count_first, (
                f"Recordings should not decrease after restart: {count_first} → {count_second}"
            )

            print(
                f"\n  ✅ Restart idempotent: {count_first} → {count_second} recordings, "
                f"0 duplicates"
            )
        finally:
            podman_stop_rm(processor_name)
            podman_stop_rm(recorder_name)

    @pytest.mark.timeout(120)
    def test_concurrent_recorders_indexed(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """Two Recorder containers produce WAV files → both indexed correctly."""
        require_recorder_image()
        require_processor_image()

        db_container, _ = system_db

        # Separate workspace directories per recorder
        workspace_a = tmp_path / "recorder" / "mic-aaa"
        workspace_b = tmp_path / "recorder" / "mic-bbb"
        workspace_root = tmp_path / "recorder"
        workspace_a.mkdir(parents=True, exist_ok=True)
        workspace_b.mkdir(parents=True, exist_ok=True)
        workspace_root.chmod(0o777)
        workspace_a.chmod(0o777)
        workspace_b.chmod(0o777)

        recorder_a = f"silvasonic-recorder-conc-a-{run_id}"
        recorder_b = f"silvasonic-recorder-conc-b-{run_id}"
        processor_name = f"silvasonic-processor-conc-{run_id}"

        try:
            # Start two Recorders writing to separate subdirectories
            for rec_name, ws in [
                (recorder_a, workspace_a),
                (recorder_b, workspace_b),
            ]:
                podman_run(
                    rec_name,
                    "localhost/silvasonic_recorder:latest",
                    env=make_recorder_env(),
                    volumes=[f"{ws}:/app/workspace:z"],
                    network=system_network,
                )

            # Wait for both to produce segments
            time.sleep(25)

            # Start Processor pointing to parent directory
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{workspace_root}:/data/recorder:z"],
                network=system_network,
            )

            time.sleep(15)

            # Query DB for recordings
            count_str = psql_query(db_container, "SELECT COUNT(*) FROM recordings")
            count = int(count_str) if count_str else 0

            sensor_str = psql_query(
                db_container,
                "SELECT DISTINCT sensor_id FROM recordings",
            )
            sensor_ids = {line.strip() for line in sensor_str.splitlines() if line.strip()}

            if count == 0:
                print(f"\n--- PROCESSOR LOGS ---\n{podman_logs(processor_name)}")
                print(f"\n--- RECORDER A LOGS ---\n{podman_logs(recorder_a)}")
                print(f"\n--- RECORDER B LOGS ---\n{podman_logs(recorder_b)}")
                print(f"\n--- WORKSPACE ---\n{list(workspace_root.rglob('*.wav'))}")

            assert count >= 2, f"Expected recordings from both recorders, got {count}"
            assert len(sensor_ids) == 2, f"Expected 2 distinct sensor_ids, got {sensor_ids}"
            assert "mic-aaa" in sensor_ids, f"mic-aaa not in sensor_ids: {sensor_ids}"
            assert "mic-bbb" in sensor_ids, f"mic-bbb not in sensor_ids: {sensor_ids}"

            print(
                f"\n  ✅ Concurrent indexing verified: {count} recordings "
                f"from sensor_ids={sensor_ids}"
            )
        finally:
            podman_stop_rm(processor_name)
            podman_stop_rm(recorder_a)
            podman_stop_rm(recorder_b)
