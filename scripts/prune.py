#!/usr/bin/env python3
"""Remove dangling (untagged) container images to reclaim disk space.

Usage:
    python3 scripts/prune.py
"""

import subprocess
import sys

from common import print_header, print_step, print_success, print_warning


def main() -> None:
    """Prune dangling container images."""
    print_header("Pruning Dangling Images")

    binary = "podman"

    # Count dangling images first
    result = subprocess.run(
        [binary, "images", "--filter", "dangling=true", "-q"],
        capture_output=True,
        text=True,
    )
    dangling = [line for line in result.stdout.strip().splitlines() if line.strip()]

    if not dangling:
        print_success("No dangling images found — nothing to prune.")
        return

    print_step(f"Found {len(dangling)} dangling image(s). Pruning...")

    prune_result = subprocess.run(
        [binary, "image", "prune", "-f"],
        capture_output=True,
        text=True,
    )

    if prune_result.returncode == 0:
        print_success(f"Pruned {len(dangling)} dangling image(s).")
        if prune_result.stdout.strip():
            print(prune_result.stdout.strip())
    else:
        print_warning(f"Prune returned exit {prune_result.returncode}.")
        if prune_result.stderr.strip():
            print(prune_result.stderr.strip())
        sys.exit(prune_result.returncode)


if __name__ == "__main__":
    main()
