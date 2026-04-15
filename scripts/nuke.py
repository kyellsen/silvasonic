#!/usr/bin/env python3
"""Full nuclear reset: clean + destroy .venv + remove all Silvasonic Podman artifacts.

Consolidates all cleanup into a single script:
  1. clean (clear + trash + compose volumes + workspace)
  2. Remove .venv
  3. Remove orphaned Silvasonic containers (test leftovers etc.)
  4. Remove Silvasonic volumes
  5. Remove Silvasonic networks
  6. Remove all Silvasonic container images

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


def _podman_list(resource: str, filter_arg: str, fmt: str) -> list[str]:
    """List Podman resources matching a filter, return non-empty lines."""
    try:
        result = run_command(
            ["podman", resource, "ls", "-a", "--filter", filter_arg, "--format", fmt]
            if resource != "network"
            else ["podman", resource, "ls", "--filter", filter_arg, "--format", fmt],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        print_error("Container engine 'podman' not found in PATH.")
        sys.exit(1)

    if result.returncode != 0:
        return []

    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def remove_silvasonic_containers() -> None:
    """Remove all containers whose name starts with 'silvasonic-'."""
    names = _podman_list("container", "name=silvasonic-", "{{.Names}}")

    if not names:
        print_success("No Silvasonic containers found.")
        return

    print_step(f"Removing {len(names)} Silvasonic container(s)...")
    for name in names:
        run_command(["podman", "rm", "-f", name], check=False)
    print_success(f"Removed {len(names)} Silvasonic container(s).")


def remove_silvasonic_volumes() -> None:
    """Remove all volumes whose name contains 'silvasonic'."""
    volumes = _podman_list("volume", "name=silvasonic", "{{.Name}}")

    if not volumes:
        print_success("No Silvasonic volumes found.")
        return

    print_step(f"Removing {len(volumes)} Silvasonic volume(s)...")
    for vol in volumes:
        run_command(["podman", "volume", "rm", "-f", vol], check=False)
    print_success(f"Removed {len(volumes)} Silvasonic volume(s).")


def remove_silvasonic_networks() -> None:
    """Remove all networks whose name contains 'silvasonic'."""
    networks = _podman_list("network", "name=silvasonic", "{{.Name}}")
    # Never remove the default "podman" network
    networks = [n for n in networks if n != "podman"]

    if not networks:
        print_success("No Silvasonic networks found.")
        return

    print_step(f"Removing {len(networks)} Silvasonic network(s)...")
    for net in networks:
        run_command(["podman", "network", "rm", "-f", net], check=False)
    print_success(f"Removed {len(networks)} Silvasonic network(s).")


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

    # 3. Remove orphaned Silvasonic containers (test leftovers etc.)
    print_step("Removing orphaned Silvasonic containers...")
    remove_silvasonic_containers()

    # 4. Remove Silvasonic volumes
    print_step("Removing Silvasonic volumes...")
    remove_silvasonic_volumes()

    # 5. Remove Silvasonic networks
    print_step("Removing Silvasonic networks...")
    remove_silvasonic_networks()

    # 6. Remove container images
    print_step("Removing Silvasonic container images...")
    remove_silvasonic_images()

    print_success("☢️  Full nuclear reset done. Run 'just setup' to rebuild.")


if __name__ == "__main__":
    main()
