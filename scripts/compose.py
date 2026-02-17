"""Shared compose-command resolver for Silvasonic developer scripts.

Reads SILVASONIC_CONTAINER_ENGINE from .env / environment and returns
the matching compose command as a list suitable for subprocess calls.

Strictly relies on the Python Standard Library (no .venv required).
"""

import os
import shutil
import sys
from pathlib import Path

from common import load_env_value, print_error

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_container_engine() -> str:
    """Resolve the container engine name (podman | docker).

    Priority: environment variable > .env file > default 'podman'.
    """
    return (
        os.environ.get("SILVASONIC_CONTAINER_ENGINE")
        or load_env_value("SILVASONIC_CONTAINER_ENGINE")
        or "podman"
    )


def get_compose_cmd() -> list[str]:
    """Return the compose command as a list for subprocess calls.

    - podman  → ["podman-compose"]
    - docker  → ["docker", "compose"]
    """
    engine = get_container_engine()

    if engine == "docker":
        cmd = ["docker", "compose"]
        binary = "docker"
    else:
        cmd = ["podman-compose"]
        binary = "podman-compose"

    if not shutil.which(binary):
        print_error(
            f"Container tool '{binary}' not found in PATH.\n"
            f"   Install it or set SILVASONIC_CONTAINER_ENGINE in .env."
        )
        sys.exit(1)

    return cmd


def compose(*args: str, check: bool = True) -> None:
    """Run a compose command with the detected engine."""
    from common import run_command

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

    # Construct final command: [tool, -f base, -f override, command, args]
    # Note: docker compose accepts flags before the command, podman-compose
    # might need verification but generally supports standard compose syntax.
    # Actually, standard `docker compose` syntax is `docker compose -f ... up`.
    # `podman-compose` syntax is `podman-compose -f ... up`.

    # We need to insert the file flags *after* "compose" but *before* the args.
    # get_compose_cmd() returns e.g. ["podman-compose"] or ["docker", "compose"]

    base_cmd = get_compose_cmd()
    cmd = base_cmd + compose_files + list(args)

    run_command(cmd, cwd=PROJECT_ROOT, check=check)
