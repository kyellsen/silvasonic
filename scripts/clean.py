#!/usr/bin/env python3
import argparse
import glob
import os
import shutil
import subprocess

from common import print_error, print_header, print_step, print_success, print_warning


def clean_artifacts() -> None:
    """Remove build artifacts and cache directories."""
    print_header("Cleaning up artifacts...")

    patterns = [
        "**/*.pyc",
        "**/__pycache__",
        ".coverage",
        "htmlcov",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        "*.egg-info",
        ".tmp",
    ]

    # Load .clean_patterns if exists
    if os.path.exists(".clean_patterns"):
        print_step("Reading clean patterns from .clean_patterns...")
        with open(".clean_patterns") as f_obj:
            for line in f_obj:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)

    for pattern in patterns:
        # Recursive glob
        files = glob.glob(pattern, recursive=True)
        for f_path in files:
            # Avoid deleting the script itself or important things if pattern is too broad
            # But standard patterns should be fine.
            try:
                if os.path.isfile(f_path) or os.path.islink(f_path):
                    os.remove(f_path)
                elif os.path.isdir(f_path):
                    shutil.rmtree(f_path)
            except Exception as e:
                print_warning(f"Failed to delete {f_path}: {e}")

    print_success("Clean complete.")


def clean_storage() -> None:
    """Delete all persistent data (Factory Reset)."""
    print_warning("FACTORY RESET: Deleting all persistent data...")
    workspace_path = os.environ.get(
        "SILVASONIC_WORKSPACE_PATH", "/mnt/data/dev_workspaces/silvasonic"
    )

    if os.path.exists(workspace_path):
        try:
            shutil.rmtree(workspace_path)
            print_success(f"Workspace deleted: {workspace_path}")
        except PermissionError:
            print_warning("Permission denied. Attempting force cleanup via `podman unshare`...")
            try:
                subprocess.run(
                    ["podman", "unshare", "rm", "-rf", workspace_path],
                    check=True,
                    capture_output=True,
                )
                print_success(f"Workspace deleted (via podman unshare): {workspace_path}")
            except Exception as e2:
                print_error(f"Failed to force delete workspace: {e2}")
                print_warning(
                    "Tip: You may need to run: podman unshare rm -rf /mnt/data/dev_workspaces/silvasonic"
                )
        except Exception as e:
            print_warning(f"Failed to delete workspace {workspace_path}: {e}")
    else:
        print_step("Workspace does not exist, nothing to delete.")

    print_step("Run 'make init' to restore structure.")


def clean_venv() -> None:
    """Delete the virtual environment."""
    print_header("Cleaning virtual environment...")
    if os.path.exists(".venv"):
        try:
            shutil.rmtree(".venv")
            print_success("Virtual environment (.venv) deleted.")
        except Exception as e:
            print_warning(f"Failed to delete .venv: {e}")
    else:
        print_step(".venv does not exist, nothing to delete.")


def main() -> None:
    """Parse arguments and clean artifacts or storage."""
    parser = argparse.ArgumentParser(description="Clean Silvasonic artifacts")
    parser.add_argument(
        "--storage", action="store_true", help="Delete persistent workspace data (Factory Reset)"
    )
    parser.add_argument("--venv", action="store_true", help="Delete virtual environment (.venv)")
    args = parser.parse_args()

    clean_artifacts()

    if args.venv:
        clean_venv()

    if args.storage:
        clean_storage()


if __name__ == "__main__":
    main()
