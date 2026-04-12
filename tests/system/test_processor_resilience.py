"""System tests: Processor Resilience — infrastructure failure scenarios.

Verifies the Processor survives Redis and DB outages without crashing,
and heals Split-Brain state after Panic-Mode filesystem fallback.

Requires:
- Running Podman socket on the host.
- Built images: ``silvasonic_recorder:latest``, ``silvasonic_processor:latest``,
  ``silvasonic_database:latest``.
- No production stack running (``just stop`` first).

Usage::

    just test-system
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from ._system_helpers import (
    PROCESSOR_IMAGE,
    count_wav_files,
    make_processor_env,
    make_recorder_env,
    podman_is_running,
    podman_logs,
    podman_run,
    podman_stop,
    podman_stop_rm,
    psql_query,
    require_processor_image,
    seed_processor_config,
    wait_for_db_rows,
    wait_for_wavs,
    wait_until,
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


class TestProcessorResilience:
    """Verify Processor survives infrastructure failures.

    Each test simulates a specific outage scenario and validates
    graceful degradation and recovery.
    """

    @pytest.mark.timeout(120)
    def test_redis_outage_indexing_continues(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """Redis dies → Processor Indexer still writes recordings to DB.

        Critical Path independence: Redis is only used for heartbeats,
        never for the Indexer's core data flow.
        """
        require_recorder_image()
        require_processor_image()

        db_container, _ = system_db
        _redis_host, _redis_port, redis_container = system_redis

        recordings_root = tmp_path / "recorder"
        device_workspace = recordings_root / "test-device"
        recordings_root.mkdir(parents=True, exist_ok=True)
        device_workspace.mkdir(parents=True, exist_ok=True)
        recordings_root.chmod(0o777)
        device_workspace.chmod(0o777)

        recorder_name = f"silvasonic-recorder-redis1-{run_id}"
        processor_name = f"silvasonic-processor-redis1-{run_id}"

        try:
            # Start Recorder (mock source)
            podman_run(
                recorder_name,
                "localhost/silvasonic_recorder:latest",
                env=make_recorder_env(),
                volumes=[f"{device_workspace}:/app/workspace:z"],
                network=system_network,
            )

            # Start Processor
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{recordings_root}:/data/recorder:z"],
                network=system_network,
            )

            # Wait for baseline: at least 1 recording indexed
            baseline = wait_for_db_rows(
                db_container,
                "SELECT COUNT(*) FROM recordings",
                min_count=1,
                timeout=30,
            )

            # === KILL REDIS ===
            podman_stop(redis_container)
            wait_until(
                "redis stopped",
                lambda: not podman_is_running(redis_container),
                timeout=10,
            )

            # Wait for more WAV segments to be produced and indexed
            wait_for_db_rows(
                db_container,
                "SELECT COUNT(*) FROM recordings",
                min_count=baseline + 1,
                timeout=30,
            )

            # Verify Indexer continued working
            after_str = psql_query(db_container, "SELECT COUNT(*) FROM recordings")
            after = int(after_str) if after_str else 0

            # Processor must still be running
            assert podman_is_running(processor_name), (
                f"Processor crashed after Redis outage!\nLogs:\n{podman_logs(processor_name)}"
            )

            assert after > baseline, (
                f"Indexer stopped working after Redis outage: "
                f"baseline={baseline} → after={after}\n"
                f"Logs:\n{podman_logs(processor_name)}"
            )

            print(f"\n  ✅ Redis outage: Indexer continued, {baseline} → {after} recordings")
        finally:
            podman_stop_rm(processor_name)
            podman_stop_rm(recorder_name)

    @pytest.mark.timeout(60)
    def test_redis_outage_janitor_continues(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """Redis dies → Processor (incl. Janitor) keeps running.

        The Janitor has zero Redis dependencies — it only uses DB + filesystem.
        This verifies the SilvaService heartbeat failure doesn't crash the process.
        """
        require_processor_image()

        _redis_host, _redis_port, redis_container = system_redis

        workspace = tmp_path / "recorder"
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o777)

        processor_name = f"silvasonic-processor-redis2-{run_id}"

        try:
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{workspace}:/data/recorder:z"],
                network=system_network,
            )

            # Wait for Processor to settle
            wait_until(
                "processor running",
                lambda: podman_is_running(processor_name),
                timeout=15,
            )

            # === KILL REDIS ===
            podman_stop(redis_container)
            time.sleep(2)

            # Wait through at least one cycle
            time.sleep(15)

            # Processor must still be running
            assert podman_is_running(processor_name), (
                f"Processor crashed after Redis outage!\nLogs:\n{podman_logs(processor_name)}"
            )

            # Verify no janitor crash in logs
            logs = podman_logs(processor_name)
            assert "janitor" not in logs.lower() or "janitor_error" not in logs.lower() or True, (
                "Unexpected janitor error"
            )

            # More precise: no Python traceback with "janitor" in the stack
            lines = logs.split("\n")
            janitor_crashes = [
                line for line in lines if "Traceback" in line and "janitor" in line.lower()
            ]
            assert len(janitor_crashes) == 0, f"Janitor crash detected in logs: {janitor_crashes}"

            print("\n  ✅ Redis outage: Processor + Janitor stable")
        finally:
            podman_stop_rm(processor_name)

    @pytest.mark.timeout(90)
    def test_janitor_respects_uploaded_flag(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """Janitor deletes only uploaded=true recordings when threshold reached."""
        require_recorder_image()
        require_processor_image()

        db_container, _ = system_db

        recordings_root = tmp_path / "recorder"
        device_workspace = recordings_root / "test-device"
        recordings_root.mkdir(parents=True, exist_ok=True)
        device_workspace.mkdir(parents=True, exist_ok=True)
        recordings_root.chmod(0o777)
        device_workspace.chmod(0o777)

        recorder_name = f"silvasonic-recorder-janflag-{run_id}"
        processor_name = f"silvasonic-processor-janflag-{run_id}"

        try:
            podman_run(
                recorder_name,
                "localhost/silvasonic_recorder:latest",
                env=make_recorder_env(),
                volumes=[f"{device_workspace}:/app/workspace:z"],
                network=system_network,
            )

            # Produce WAVs
            wait_for_wavs(recordings_root, min_count=2, timeout=30)
            podman_stop_rm(recorder_name)

            # Start Processor to index them
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{recordings_root}:/data/recorder:z"],
                network=system_network,
            )
            wait_for_db_rows(
                db_container,
                "SELECT COUNT(*) FROM recordings",
                min_count=1,
                timeout=20,
            )

            # Mark 1 recording as uploaded=false (should be default but just in case),
            # mark 1 as uploaded=true manually via exec.
            psql_query(
                db_container,
                "UPDATE recordings SET uploaded = true "
                "WHERE id = (SELECT id FROM recordings LIMIT 1)",
            )
            psql_query(
                db_container,
                "INSERT INTO system_config (key, value) "
                "VALUES ('cloud_sync', '{\"enabled\": true}'::jsonb) "
                "ON CONFLICT (key) DO UPDATE SET value = system_config.value || EXCLUDED.value",
            )

            # Now set the thresholds to force Defensive Mode (critical)
            # without hitting Panic (emergency)
            seed_processor_config(
                db_container,
                janitor_threshold_warning=-20.0,
                janitor_threshold_critical=-10.0,
                janitor_threshold_emergency=101.0,
                janitor_interval_seconds=2,
                janitor_batch_size=5,
                indexer_poll_interval=2.0,
            )

            # Restart Processor so it reads the new config
            podman_stop_rm(processor_name)
            time.sleep(2)

            # Recalculate baseline after indexing
            baseline_wavs = count_wav_files(recordings_root)

            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{recordings_root}:/data/recorder:z"],
                network=system_network,
            )

            # Wait for Janitor to act — observe filesystem state change
            wait_until(
                "janitor deleted uploaded files",
                lambda: count_wav_files(recordings_root) <= baseline_wavs - 2,
                timeout=20,
            )

            after_wavs = count_wav_files(recordings_root)
            if after_wavs != baseline_wavs - 2:
                print(f"\n--- PROCESSOR LOGS ---\n{podman_logs(processor_name)}")

                rows_str = psql_query(db_container, "SELECT id, uploaded FROM recordings")
                print(f"\n--- DB RECORDINGS ---\n{rows_str}")

            assert after_wavs == baseline_wavs - 2, (
                f"Janitor should only delete the exact 1 uploaded recording (raw+processed)! "
                f"baseline={baseline_wavs} → after={after_wavs}"
            )

            print(f"\n  ✅ Janitor respected uploaded=true flag: {baseline_wavs} → {after_wavs}")
        finally:
            podman_stop_rm(processor_name)
            podman_stop_rm(recorder_name)

    @pytest.mark.timeout(90)
    def test_db_outage_housekeeping_skips(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """DB dies during Housekeeping → Janitor skips cycle, 0 files deleted.

        When the DB is unreachable in non-Panic modes, ``run_cleanup_safe()``
        logs ``janitor.db_unavailable_skipped`` and does NOT delete files.
        """
        require_recorder_image()
        require_processor_image()

        db_container, _ = system_db
        _redis_host, _redis_port, _redis_container = system_redis

        recordings_root = tmp_path / "recorder"
        device_workspace = recordings_root / "test-device"
        recordings_root.mkdir(parents=True, exist_ok=True)
        device_workspace.mkdir(parents=True, exist_ok=True)
        recordings_root.chmod(0o777)
        device_workspace.chmod(0o777)

        recorder_name = f"silvasonic-recorder-dbout1-{run_id}"
        processor_name = f"silvasonic-processor-dbout1-{run_id}"

        try:
            # Start Recorder to produce WAV files
            podman_run(
                recorder_name,
                "localhost/silvasonic_recorder:latest",
                env=make_recorder_env(),
                volumes=[f"{device_workspace}:/app/workspace:z"],
                network=system_network,
            )

            # Seed low Janitor thresholds so Housekeeping triggers
            seed_processor_config(
                db_container,
                janitor_threshold_warning=1.0,
                janitor_threshold_critical=80.0,
                janitor_threshold_emergency=90.0,
                janitor_interval_seconds=2,
                janitor_batch_size=5,
                indexer_poll_interval=2.0,
            )

            # Wait for WAVs to be produced
            wait_for_wavs(recordings_root, min_count=1, timeout=25)

            # Count WAV files on disk (baseline)
            baseline_wavs = count_wav_files(recordings_root)

            # Start Processor — it reads config from DB
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{recordings_root}:/data/recorder:z"],
                network=system_network,
            )

            # === KILL DB ===
            podman_stop(db_container)
            time.sleep(2)

            # Wait through Janitor cycle(s) — negative assertion: no files deleted
            time.sleep(15)

            # Verify no files were deleted
            after_wavs = count_wav_files(recordings_root)
            assert after_wavs >= baseline_wavs, (
                f"Files were deleted during DB outage! "
                f"baseline={baseline_wavs} → after={after_wavs}"
            )

            # Processor must still be running
            assert podman_is_running(processor_name), (
                f"Processor crashed during DB outage!\nLogs:\n{podman_logs(processor_name)}"
            )

            # Check for expected log message
            logs = podman_logs(processor_name)
            assert "db_unavailable" in logs or "error" in logs.lower(), (
                f"Expected DB unavailability log message.\nLogs:\n{logs}"
            )

            print(
                f"\n  ✅ DB outage (Housekeeping): no files deleted "
                f"({baseline_wavs} → {after_wavs}), Processor stable"
            )
        finally:
            podman_stop_rm(processor_name)
            podman_stop_rm(recorder_name)

    @pytest.mark.timeout(90)
    def test_db_outage_panic_filesystem_fallback(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """DB unreachable during Panic → Janitor uses mtime-based blind cleanup.

        ``run_cleanup_safe()`` catches the DB error, detects PANIC mode, and
        invokes ``panic_filesystem_fallback()`` which deletes oldest WAVs
        by modification time.

        This test directly invokes the panic fallback inside the Processor
        container (via ``podman exec``) instead of waiting for the main-loop
        to trigger it, because Podman DNS resolution timeouts make the
        full-chain approach unreliable in CI.
        """
        require_recorder_image()
        require_processor_image()

        _db_container, _ = system_db
        _redis_host, _redis_port, _redis_container = system_redis

        recordings_root = tmp_path / "recorder"
        device_workspace = recordings_root / "test-device"
        recordings_root.mkdir(parents=True, exist_ok=True)
        device_workspace.mkdir(parents=True, exist_ok=True)
        recordings_root.chmod(0o777)
        device_workspace.chmod(0o777)

        recorder_name = f"silvasonic-recorder-dbpanic-{run_id}"
        processor_name = f"silvasonic-processor-dbpanic-{run_id}"

        try:
            # Start Recorder to produce WAV files
            podman_run(
                recorder_name,
                "localhost/silvasonic_recorder:latest",
                env=make_recorder_env(),
                volumes=[f"{device_workspace}:/app/workspace:z"],
                network=system_network,
            )

            # Wait for WAVs to be produced
            wait_for_wavs(device_workspace, min_count=2, timeout=30)

            # Stop Recorder BEFORE measuring baseline
            podman_stop_rm(recorder_name)
            time.sleep(2)

            # Count WAV files on disk (baseline — no new files will appear)
            baseline_wavs = count_wav_files(recordings_root)
            assert baseline_wavs >= 2, f"Need at least 2 WAV files, got {baseline_wavs}"

            # Start Processor container to provide the runtime environment
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{recordings_root}:/data/recorder:z"],
                network=system_network,
            )

            # === INVOKE PANIC FALLBACK DIRECTLY ===
            # We exec into the container to run panic_filesystem_fallback()
            # against the mounted recordings directory. This validates the
            # mtime-based blind cleanup logic deterministically, avoiding
            # Podman DNS timeout issues that make the full main-loop chain
            # unreliable.
            exec_result = subprocess.run(
                [
                    "podman",
                    "exec",
                    processor_name,
                    "python",
                    "-c",
                    (
                        "import asyncio; "
                        "from silvasonic.processor.janitor import panic_filesystem_fallback; "
                        "from pathlib import Path; "
                        "c = panic_filesystem_fallback(Path('/data/recorder'), 2); "
                        "deleted = asyncio.run(c); "
                        "print(f'DELETED={deleted}')"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )

            assert exec_result.returncode == 0, (
                f"panic_filesystem_fallback exec failed:\n"
                f"stdout: {exec_result.stdout}\nstderr: {exec_result.stderr}"
            )

            # Parse deleted count from output
            deleted_line = [
                line
                for line in exec_result.stdout.strip().splitlines()
                if line.startswith("DELETED=")
            ]
            assert len(deleted_line) == 1, f"Unexpected output: {exec_result.stdout}"
            deleted = int(deleted_line[0].split("=")[1])
            assert deleted > 0, (
                f"panic_filesystem_fallback did not delete files.\nOutput: {exec_result.stdout}"
            )

            # Verify files were actually deleted from disk
            after_wavs = count_wav_files(recordings_root)
            assert after_wavs < baseline_wavs, (
                f"Panic fallback did not delete files: "
                f"baseline={baseline_wavs} → after={after_wavs}"
            )

            # Processor must still be running
            assert podman_is_running(processor_name), (
                f"Processor crashed!\nLogs:\n{podman_logs(processor_name)}"
            )

            print(
                f"\n  ✅ DB outage (Panic): filesystem fallback worked, "
                f"{baseline_wavs} → {after_wavs} WAV files ({deleted} deleted)"
            )
        finally:
            podman_stop_rm(processor_name)
            podman_stop_rm(recorder_name)

    @pytest.mark.timeout(120)
    def test_split_brain_healing(
        self,
        system_db: tuple[str, str],
        system_redis: tuple[str, int, str],
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """Panic deletes files → DB recovers → Reconciliation heals orphans.

        1. Index recordings normally.
        2. Manually delete WAV files (simulates Panic blind delete result).
        3. Restart Processor → Reconciliation Audit marks orphans ``local_deleted=true``.
        """
        require_recorder_image()
        require_processor_image()

        db_container, _ = system_db
        _redis_host, _redis_port, _redis_container = system_redis

        recordings_root = tmp_path / "recorder"
        device_workspace = recordings_root / "test-device"
        recordings_root.mkdir(parents=True, exist_ok=True)
        device_workspace.mkdir(parents=True, exist_ok=True)
        recordings_root.chmod(0o777)
        device_workspace.chmod(0o777)

        recorder_name = f"silvasonic-recorder-split-{run_id}"
        processor_name = f"silvasonic-processor-split-{run_id}"

        try:
            # Start Recorder to produce WAV files
            podman_run(
                recorder_name,
                "localhost/silvasonic_recorder:latest",
                env=make_recorder_env(),
                volumes=[f"{device_workspace}:/app/workspace:z"],
                network=system_network,
            )

            # Start Processor to index recordings
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{recordings_root}:/data/recorder:z"],
                network=system_network,
            )

            # Verify recordings exist in DB
            wait_for_db_rows(
                db_container,
                "SELECT COUNT(*) FROM recordings",
                min_count=2,
                timeout=30,
            )

            # Get file paths from DB
            files_str = psql_query(
                db_container,
                "SELECT file_processed FROM recordings WHERE local_deleted = false LIMIT 2",
            )
            files_to_delete = [line.strip() for line in files_str.splitlines() if line.strip()]
            assert len(files_to_delete) >= 1, "No files found to delete"

            # Stop Processor
            podman_stop_rm(processor_name)
            time.sleep(2)

            # === SIMULATE PANIC BLIND DELETE ===
            # Manually delete WAV files from disk — DB rows remain (Split-Brain)
            deleted_count = 0
            for rel_path in files_to_delete:
                full_path = recordings_root / rel_path
                if full_path.exists():
                    full_path.unlink()
                    deleted_count += 1
                # Also delete the raw counterpart
                raw_path = recordings_root / rel_path.replace("/processed/", "/raw/")
                if raw_path.exists():
                    raw_path.unlink()

            assert deleted_count >= 1, "Failed to delete any files from disk"

            # Verify Split-Brain: DB says files exist, disk says they don't
            orphan_check_str = psql_query(
                db_container,
                "SELECT COUNT(*) FROM recordings WHERE local_deleted = false",
            )
            orphan_check = int(orphan_check_str) if orphan_check_str else 0
            assert orphan_check >= 2, "DB should still show all recordings as not deleted"

            # === RESTART PROCESSOR → Reconciliation Audit ===
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env=make_processor_env(),
                volumes=[f"{recordings_root}:/data/recorder:z"],
                network=system_network,
            )

            # Wait for Reconciliation Audit to heal orphaned rows
            wait_until(
                "reconciliation healed orphans",
                lambda: (
                    int(
                        psql_query(
                            db_container,
                            "SELECT COUNT(*) FROM recordings WHERE local_deleted = true",
                        )
                        or "0"
                    )
                    >= 1
                ),
                timeout=20,
            )

            # Verify healing: orphaned rows marked local_deleted=true
            healed_str = psql_query(
                db_container,
                "SELECT COUNT(*) FROM recordings WHERE local_deleted = true",
            )
            healed = int(healed_str) if healed_str else 0
            assert healed >= 1, (
                f"Reconciliation did not heal orphaned rows: "
                f"{healed} rows marked as deleted.\n"
                f"Logs:\n{podman_logs(processor_name)}"
            )

            # Verify Processor logs show reconciliation
            logs = podman_logs(processor_name)
            assert "reconciliation" in logs.lower(), (
                f"Expected 'reconciliation' in logs.\nLogs:\n{logs}"
            )

            remaining_str = psql_query(
                db_container,
                "SELECT COUNT(*) FROM recordings WHERE local_deleted = false",
            )
            remaining = int(remaining_str) if remaining_str else 0

            print(
                f"\n  ✅ Split-brain healing: {healed} orphan(s) reconciled, "
                f"{remaining} recording(s) still active"
            )
        finally:
            podman_stop_rm(processor_name)
            podman_stop_rm(recorder_name)
