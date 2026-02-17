#!/usr/bin/env python3
"""Medium cleanup: clear + empty trash + container volumes + workspace wipe.

The .venv directory is preserved (use 'just nuke' to remove it).

Usage:
    python scripts/clean.py              # normal run
    python scripts/clean.py --dry-run    # preview only, nothing is deleted
"""

import shutil
import sys
from pathlib import Path

# Re-use clear logic
from clear import empty_trash
from clear import main as clear_main
from common import get_workspace_path, print_header, print_step, print_success, print_warning
from compose import compose

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def remove_workspace(dry_run: bool = False) -> None:
    """Remove the workspace directory (path from .env)."""
    workspace_dir = get_workspace_path()

    if not workspace_dir.exists():
        print_success(f"Workspace directory does not exist: {workspace_dir}")
        return

    if dry_run:
        print_warning(f"[DRY-RUN] Would delete workspace: {workspace_dir}")
        return

    shutil.rmtree(workspace_dir, ignore_errors=True)
    print_success(f"Removed workspace directory: {workspace_dir}")


def main() -> None:
    """Run the full clean pipeline."""
    dry_run = "--dry-run" in sys.argv

    # --- Stage 1: clear (root quarantine + caches) ---
    clear_main(dry_run=dry_run)

    # --- Stage 2: Empty trash ---
    print_header("Clean - Empty Trash" + (" (DRY-RUN)" if dry_run else ""))
    print_step("Emptying .trash/ directory...")
    empty_trash(dry_run=dry_run)

    # --- Stage 3: Container storage ---
    print_header("Clean - Storage Reset" + (" (DRY-RUN)" if dry_run else ""))

    print_step("Stopping containers and removing volumes...")
    if dry_run:
        print_warning("[DRY-RUN] Would run: compose down -v")
    else:
        compose("down", "-v", check=False, quiet=True)

    # --- Stage 4: Workspace ---
    print_step("Removing workspace directory...")
    remove_workspace(dry_run=dry_run)

    print_success("Clean complete.")


if __name__ == "__main__":
    main()
