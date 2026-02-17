#!/usr/bin/env python3
"""Initialize the Silvasonic development environment.

Relies on common.py for styling and OS-level operations.
"""

import os
import shutil
import sys
from pathlib import Path

from common import (
    Colors,
    check_group_membership,
    ensure_dir,
    get_workspace_path,
    print_error,
    print_header,
    print_step,
    print_success,
    print_warning,
    run_command,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent


def load_workspace_dirs() -> list[str]:
    """Load workspace subdirectory paths from workspace_dirs.txt.

    Returns a list of relative path strings (e.g. ['controller', 'recorder']).
    Lines starting with '#' and blank lines are ignored.
    """
    config_file = SCRIPTS_DIR / "workspace_dirs.txt"
    if not config_file.exists():
        print_error(f"Workspace directory config not found: {config_file}")
        sys.exit(1)

    dirs: list[str] = []
    for line in config_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        dirs.append(stripped)
    return dirs


def ensure_env_file() -> None:
    """Ensure .env exists, created from .env.example if necessary."""
    env_file = PROJECT_ROOT / ".env"
    env_example = PROJECT_ROOT / ".env.example"

    # .env.example MUST exist - it's the canonical template
    if not env_example.exists():
        print_error(".env.example not found - cannot bootstrap environment. Aborting!")
        sys.exit(1)

    if env_file.exists():
        print_success(f".env already exists: {env_file}")
        return

    shutil.copy2(env_example, env_file)
    print_warning("Created .env from .env.example - please review and adjust values!")


def check_container_engine() -> None:
    """Verify that the configured container engine is available. Abort if not.

    Uses compose.py's get_container_engine() which reads .env as fallback,
    so the engine setting works even when the var isn't exported in the shell.
    """
    from compose import get_container_engine

    engine = get_container_engine()

    if shutil.which(engine):
        print_success(f"Container engine '{engine}' found.")
        return

    print_error(
        f"Container engine '{engine}' not found in PATH!\n"
        f"   Install '{engine}' or set SILVASONIC_CONTAINER_ENGINE in .env.\n"
        f"   Container commands (make build/start/stop) require a working engine."
    )
    sys.exit(1)


def main() -> None:
    """Main initialization routine."""
    print_header("Initializing Silvasonic Development Environment")

    # 1. Environment File
    print_step("Checking .env file...")
    ensure_env_file()

    # 2. Container Engine
    print_step("Checking container engine availability...")
    check_container_engine()

    # 3. Dependency Sync (uv)
    print_step("Syncing dependencies (uv)...")
    if not shutil.which("uv"):
        print_error(
            "'uv' is not installed!\n"
            "   Install via:  curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            "   Then restart your shell and re-run:  make init"
        )
        sys.exit(1)

    run_command(["uv", "sync"])
    print_success("Dependencies synced and virtual environment created.")

    # 4. Git Hooks
    print_step("Installing Pre-Commit Hooks...")
    run_command(
        [
            "uv",
            "run",
            "pre-commit",
            "install",
            "--hook-type",
            "pre-commit",
            "--hook-type",
            "pre-push",
        ]
    )
    print_success("Git hooks installed.")

    # 5. Workspace Setup (Two-Worlds Architecture)
    print_step("Setting up Workspace (Two-Worlds Architecture)...")
    workspace_dir = get_workspace_path()

    # Create workspace root
    ensure_dir(workspace_dir)

    # Create all subdirectories from external config
    workspace_dirs = load_workspace_dirs()
    for d in workspace_dirs:
        folder_path = ensure_dir(workspace_dir / d)
        print(f"   Created/Verified: {folder_path}")

    print_success(f"Workspace ready at: {workspace_dir} (Permissions: 755)")

    # 6. Hardware Access Verification (Raspberry Pi specific)
    print_step("Verifying Hardware Access Groups...")
    required_groups = ["audio", "gpio", "spi", "i2c", "dialout"]
    not_configured = []

    user = os.environ.get("USER", "root")

    for group in required_groups:
        is_in_db, is_active = check_group_membership(group, user)

        if is_active:
            print(f"   ✅ User '{user}' is in '{group}' (active)")
        elif is_in_db:
            print(f"   🔄 User '{user}' is in '{group}' (database).")
            warn = Colors.WARNING
            end = Colors.ENDC
            msg = f"      {warn}Action: Re-login or reboot required to activate!{end}"
            print(msg)
        else:
            print(f"   ⚠️  WARNING: User '{user}' is NOT in '{group}'.")
            not_configured.append(group)

    if not_configured:
        print_error("PLEASE FIX: Run the following command to add missing groups:")
        print(f"{Colors.BOLD}sudo usermod -aG {','.join(not_configured)} {user}{Colors.ENDC}")
    else:
        print_success("Hardware group verification passed.")

    print_header("Initialization Complete! 🎉")


if __name__ == "__main__":
    main()
