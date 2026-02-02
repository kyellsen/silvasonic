#!/usr/bin/env python3
"""scripts/init.py.

Initializes the Silvasonic development environment in strict compliance with
docs/architecture/filesystem_governance.md.

Roles:
1. Enforce "Two-Worlds" architecture (Repository vs Workspace).
2. Create standard Domain-Driven Directory Structure.
3. Ensure 'logs' directories exist for all services.
4. Set permissions (755) for Rootless Podman compatibility.
"""

import os
import shutil
import subprocess
import sys

from common import (
    ensure_dir,
    print_error,
    print_header,
    print_step,
    print_success,
    print_warning,
    run_command,
)


def main() -> None:
    """Initialize the Silvasonic development environment."""
    print_header("Initializing Silvasonic Development Environment...")

    # 1. Python Dependencies
    print_step("Syncing dependencies (uv)...")
    if not shutil.which("uv"):
        print_error("uv is not installed. Please install uv first.")
        sys.exit(1)

    run_command(["uv", "sync"])
    print_success("Dependencies synced.")

    # 2. Git Hooks
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

    # 3. Workspace Structure
    print_step("Checking Workspace Root (Two-Worlds Compliance)...")
    # Governance: SILVASONIC_WORKSPACE_PATH must remain separate from Repo.
    workspace_dir = os.environ.get(
        "SILVASONIC_WORKSPACE_PATH", "/mnt/data/dev_workspaces/silvasonic"
    )
    ensure_dir(workspace_dir)
    print_success(f"Workspace directory checked: {workspace_dir}")

    # 3b. Create Service Subdirectories
    # Governance: "The Workspace directory must be strictly organized by service."
    print_step("Creating Domain-Driven Directory Structure...")
    required_service_dirs = [
        # Persistence Stores
        "database",
        "redis",
        # Service Working Directories
        "recorder",  # Parent for dynamic mic folders (e.g. recorder/ultramic_1/)
        "processor/artifacts",
        "uploader/buffer",
        # Gateway (Caddy)
        "gateway/config",
        "gateway/data",
        "gateway/logs",
        # Logging Directories (Mandatory for all services)
        "controller/logs",
        # "recorder/logs",  # Shared/Fallback log dir (individual mics use subdirs via Orchestrator)
        "processor/logs",
        "uploader/logs",
        "monitor/logs",
        "status-board/logs",
        # Optional/Future Services
        "birdnet/logs",
        "batdetect/logs",
        "weather/logs",
        "web-interface/logs",
    ]

    for sub_dir in required_service_dirs:
        full_path = os.path.join(workspace_dir, sub_dir)
        ensure_dir(full_path)
        print(f"   Created/Verified: {sub_dir}")

    # 4. Permissions
    # Governance: "It must ensure all folders are owned by the host user and have 755 (rwxr-xr-x) permissions."
    print_step("Enforcing Workspace Permissions (755)...")
    try:
        # We recursively set permissions to ensure containers (mapped to keep-id) can write.
        run_command(["chmod", "-R", "755", workspace_dir])
    except Exception as e:
        print_error(f"Failed to set permissions: {e}")
    print_success("Permissions set.")

    # 5. Hardware Access Verify
    print_step("Verifying Hardware Access Groups...")
    # Required for accessing /dev/snd, GPIO, etc.
    required_groups = ["audio", "gpio", "spi", "i2c", "dialout"]
    not_configured = []

    user = os.environ.get("USER", "root")

    for group in required_groups:
        # Check active groups (current session)
        active_groups_cmd = subprocess.run(["id", "-Gn"], capture_output=True, text=True)
        active_groups = active_groups_cmd.stdout.split()

        # Check potential groups (database)
        user_groups_cmd = subprocess.run(["id", "-Gn", user], capture_output=True, text=True)
        user_groups = user_groups_cmd.stdout.split()

        if group in active_groups:
            print(f"   ✅ User is in '{group}' (active)")
        elif group in user_groups:
            print(f"   🔄 User is in '{group}' (database) but NOT active in this shell.")
            print_warning(f"Group '{group}' pending reboot/logout.")
        else:
            print(f"   ⚠️  WARNING: User is NOT in '{group}' group.")
            not_configured.append(group)

    if not_configured:
        print_error(
            f"PLEASE FIX: Create groups or add user: sudo usermod -aG {','.join(not_configured)} $USER"
        )

    print_success("Initialization complete.")


if __name__ == "__main__":
    main()
