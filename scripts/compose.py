"""Shared compose-command helper for Silvasonic developer scripts.

Podman-only (see ADR-0004, ADR-0013).
Provides a single `compose()` function that runs podman-compose
with the correct compose files and error handling.

Strictly relies on the Python Standard Library (no .venv required).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from common import load_env_value, print_error, run_command

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def compose(*args: str, check: bool = True, quiet: bool = False) -> None:
    """Run a podman-compose command.

    Args:
        *args: Arguments to pass to podman-compose.
        check: If True, exit on failure.
        quiet: If True, suppress stderr (useful for cleanup where
               'no container found' errors are expected and harmless).
    """
    binary = "podman-compose"
    if not shutil.which(binary):
        print_error(
            f"'{binary}' not found in PATH.\n"
            f"   Install it: https://github.com/containers/podman-compose"
        )
        sys.exit(1)

    # Determine compose files based on Development Mode
    env_dev_mode = os.environ.get("SILVASONIC_DEVELOPMENT_MODE")
    env_file_dev_mode = load_env_value("SILVASONIC_DEVELOPMENT_MODE")
    dev_mode = (env_dev_mode or env_file_dev_mode or "").lower() == "true"

    compose_files = ["-f", "compose.yml"]
    if dev_mode:
        print(
            "\033[93m⚠️  Development Mode Enabled: "
            "Hot-reloading active (compose.override.yml loaded).\033[0m"
        )
        compose_files.extend(["-f", "compose.override.yml"])

    cmd = [binary, *compose_files, *args]

    if quiet:
        subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            check=False,
            stderr=subprocess.DEVNULL,
        )
    else:
        run_command(cmd, cwd=PROJECT_ROOT, check=check)
