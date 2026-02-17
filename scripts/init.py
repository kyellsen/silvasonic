#!/usr/bin/env python3
"""scripts/init.py

Initializes the Silvasonic development environment.
Relies on common.py for styling and OS-level operations.
"""

import os
import shutil
import sys
from pathlib import Path

# Wir importieren alles aus unserer eigenen common.py
from common import (
    Colors,
    check_group_membership,
    ensure_dir,
    print_error,
    print_header,
    print_step,
    print_success,
    print_warning,
    run_command,
)


def main() -> None:
    """Main initialization routine."""
    print_header("Initializing Silvasonic Development Environment")

    # 1. Dependency Sync (uv)
    print_step("Syncing dependencies (uv)...")
    if not shutil.which("uv"):
        print_error("'uv' is not installed. Please install it first (e.g., curl -LsSf https://astral.sh/uv/install.sh | sh).")
        sys.exit(1)
    
    run_command(["uv", "sync"])
    print_success("Dependencies synced and virtual environment created.")

    # 2. Git Hooks
    print_step("Installing Pre-Commit Hooks...")
    run_command(["uv", "run", "pre-commit", "install", "--hook-type", "pre-commit", "--hook-type", "pre-push"])
    print_success("Git hooks installed.")

    # 3. Generic Workspace Setup
    print_step("Setting up Generic Workspace (Two-Worlds Architecture)...")
    workspace_env = os.environ.get("SILVASONIC_WORKSPACE_PATH", ".workspace")
    workspace_dir = Path(workspace_env).resolve()

    generic_dirs = ["logs", "data", "config", "run"]
    
    # ensure_dir macht die ganze Arbeit (erstellen + 755 Rechte setzen)
    ensure_dir(workspace_dir)
    for d in generic_dirs:
        folder_path = ensure_dir(workspace_dir / d)
        print(f"   Created/Verified: {folder_path}")

    print_success(f"Workspace ready at: {workspace_dir} (Permissions: 755)")

    # 4. Hardware Access Verification (Raspberry Pi specific)
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
            print(f"      {Colors.WARNING}Action: Re-login or reboot required to activate!{Colors.ENDC}")
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