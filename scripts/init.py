#!/usr/bin/env python3
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
    print_step("Checking Workspace Root...")
    workspace_dir = os.environ.get(
        "SILVASONIC_WORKSPACE_PATH", "/mnt/data/dev_workspaces/silvasonic"
    )
    ensure_dir(workspace_dir)
    print_success(f"Workspace directory checked: {workspace_dir}")

    # 3b. Create Service Subdirectories
    print_step("Creating Domain-Driven Directory Structure...")
    required_service_dirs = [
        "database",
        "redis",
        "recorder",
        "processor/artifacts",
        "uploader/buffer",
        "gateway/config",
        "gateway/data",
        "gateway/logs",
        # Logs folders for services that don't have dedicated data folders yet
        "controller/logs",
        "recorder/logs",
        "processor/logs",
        "uploader/logs",
        "monitor/logs",
        "status-board/logs",
    ]

    for sub_dir in required_service_dirs:
        full_path = os.path.join(workspace_dir, sub_dir)
        ensure_dir(full_path)
        print(f"   Created/Verified: {sub_dir}")

    # 4. Permissions
    print_step("Enforcing Workspace Permissions (755)...")
    try:
        # Just setting the root dir for now, recursive might be slow or intrusive if plenty of data
        # The bash script did chmod -R, which is aggressive. Let's replicate it but be careful?
        # Replicating existing behavior:
        run_command(["chmod", "-R", "755", workspace_dir])
        # Note: os.chmod matches run_command chmod generally, but -R needs os.walk.
        # Calling chmod binary is fine and arguably faster for -R
    except Exception as e:
        print_error(f"Failed to set permissions: {e}")
    print_success("Permissions set.")

    # 5. Services Permissions (Scripts)
    # The old init.sh did: chmod +x scripts/*.sh. We are moving to .py, so maybe not needed?
    # But files in scripts/ might still need +x if we want to run them directly.
    # Let's assume we run via python scripts/foo.py or make calls them.
    # But for good measure:
    # for script in os.listdir("scripts"):
    #     if script.endswith(".py"):
    #         os.chmod(os.path.join("scripts", script), 0o755)

    # 6. Hardware Access Verify
    print_step("Verifying Hardware Access Groups...")
    required_groups = ["audio", "gpio", "spi", "i2c", "dialout"]
    not_configured = []

    # We can check current process groups or DB database
    # os.getgroups() checks ONLY checking active groups of current process.
    # 'id -Gn' checks both.

    # Let's use 'id' to be robust matching the bash script behavior (checking active vs potential)
    user = os.environ.get("USER", "root")

    for group in required_groups:
        # Check active
        active_groups_cmd = subprocess.run(["id", "-Gn"], capture_output=True, text=True)
        active_groups = active_groups_cmd.stdout.split()

        # Check potential (db)
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
