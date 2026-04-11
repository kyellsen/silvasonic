"""System tests: Watchdog recovery flow.

Validates that the recorder container explicitly exits with a non-zero code
when the internal watchdog exhausts its restart budget.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from ._system_helpers import (
    make_recorder_env,
    podman_logs,
    podman_run,
    podman_stop_rm,
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


class TestRecorderWatchdogRecovery:
    """Verify Recorder Watchdog container exit behavior."""

    @pytest.mark.timeout(60)
    def test_recorder_exits_on_watchdog_exhaustion(
        self,
        system_network: str,
        tmp_path: Path,
        run_id: str,
    ) -> None:
        """Recorder exits with non-zero code after multiple FFmpeg failures.

        This proves Issue 004 is properly addressed: the watchdog raises
        an exception after `max_restarts`, causing the container to crash
        rather than exiting with code 0.
        """
        require_recorder_image()

        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o777)

        recorder_name = f"silvasonic-recorder-wd-{run_id}"

        # Customize environment to ensure rapid reproducible crashes
        env = make_recorder_env()
        # Force an ALSA failure instead of using the mock sine wave source
        env["SILVASONIC_RECORDER_MOCK_SOURCE"] = "false"
        env["SILVASONIC_RECORDER_DEVICE"] = "hw:invalid_device_should_fail,99"

        # Accelerate watchdog checking so the test completes quickly
        env["SILVASONIC_RECORDER_WATCHDOG_MAX_RESTARTS"] = "2"
        env["SILVASONIC_RECORDER_WATCHDOG_CHECK_INTERVAL_S"] = "0.5"
        env["SILVASONIC_RECORDER_WATCHDOG_BASE_BACKOFF_S"] = "0.1"

        # We don't strictly need a database for the recorder to run, but the
        # network isolated environment matters

        try:
            podman_run(
                recorder_name,
                "localhost/silvasonic_recorder:latest",
                env=env,
                volumes=[f"{workspace}:/app/workspace:z"],
                network=system_network,
            )

            # Wait for the container to exit
            exited = False
            exit_code = 0
            for _ in range(40):  # Wait max 20 seconds
                result = subprocess.run(
                    [
                        "podman",
                        "inspect",
                        "--format",
                        "{{.State.Running}}|{{.State.ExitCode}}",
                        recorder_name,
                    ],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    state_raw = result.stdout.strip()
                    if state_raw:
                        is_running, code_str = state_raw.split("|")
                        if is_running == "false":
                            exited = True
                            exit_code = int(code_str)
                            break
                time.sleep(0.5)

            logs = podman_logs(recorder_name)

            assert exited, (
                f"Recorder container never exited after watchdog exhaustion.\nLogs:\n{logs}"
            )

            # Watchdog should log "watchdog.giving_up"
            assert "watchdog.giving_up" in logs, f"Did not see giving_up in logs:\n{logs}"

            # Python should raise RuntimeError
            assert "RuntimeError" in logs or "Traceback" in logs, (
                f"Did not see exception in logs:\n{logs}"
            )

            # And the critical part: Podman should report a non-zero exit code!
            assert exit_code != 0, (
                f"Recorder exited with code {exit_code} instead of non-zero error code!"
            )

        finally:
            podman_stop_rm(recorder_name)
