#!/usr/bin/env python3
"""Full nuclear reset: clean + destroy .venv + remove all Silvasonic images.

Consolidates all cleanup into a single script:
  1. clean (clear + trash + volumes + workspace)
  2. Remove .venv
  3. Remove all Silvasonic container images

Podman-only (see ADR-0004, ADR-0013).
"""

import shutil
import sys
from pathlib import Path

from common import print_error, print_header, print_step, print_success, run_command

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def remove_venv() -> None:
    """Remove the virtual environment directory."""
    venv_dir = PROJECT_ROOT / ".venv"
    if not venv_dir.exists():
        print_success(".venv does not exist — nothing to remove.")
        return

    shutil.rmtree(venv_dir, ignore_errors=True)
    print_success("☢️  .venv destroyed.")


def remove_silvasonic_images() -> None:
    """Remove all container images whose repository name contains 'silvasonic'."""
    engine = "podman"

    print_step("Searching for Silvasonic container images...")

    # List all images in "repo:tag" format
    try:
        result = run_command(
            [engine, "images", "--format", "{{.Repository}}:{{.Tag}}"],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        print_error(f"Container engine '{engine}' not found in PATH.")
        sys.exit(1)

    if result.returncode != 0:
        print_error(f"Could not list images: {result.stderr}")
        sys.exit(1)

    # Filter for silvasonic images (case-insensitive)
    all_images = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    silvasonic_images = [img for img in all_images if "silvasonic" in img.lower()]

    if not silvasonic_images:
        print_success("No Silvasonic images found.")
        return

    print_step(f"Removing {len(silvasonic_images)} Silvasonic image(s)...")
    for img in silvasonic_images:
        run_command([engine, "rmi", "-f", img], check=False)

    print_success("Silvasonic images removed.")


def main() -> None:
    """Run the full nuclear reset pipeline."""
    print_header("☢️  Nuclear Reset")

    # 1. Full clean (clear + trash + volumes + workspace)
    print_step("Running clean pipeline...")
    import clean

    clean.main()

    # 2. Destroy virtual environment
    print_step("Removing virtual environment...")
    remove_venv()

    # 3. Remove container images
    print_step("Removing Silvasonic container images...")
    remove_silvasonic_images()

    print_success("☢️  Full nuclear reset done. Run 'just init' to rebuild.")


if __name__ == "__main__":
    main()
