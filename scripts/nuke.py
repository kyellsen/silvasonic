#!/usr/bin/env python3
"""Full reset: remove all Silvasonic container images.

Called by 'make nuke' after clean + .venv removal.

Uses compose.py's get_container_engine() to stay consistent
with the single engine-detection logic.
"""

import sys

from common import print_error, print_header, print_step, print_success, run_command
from compose import get_container_engine


def remove_silvasonic_images() -> None:
    """Remove all container images whose repository name contains 'silvasonic'."""
    engine = get_container_engine()

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
    """Run the full nuke pipeline."""
    print_header("Nuclear Reset — Removing Silvasonic Images")
    remove_silvasonic_images()


if __name__ == "__main__":
    main()
