#!/usr/bin/env python3
"""Build all Silvasonic container images via compose build.

Each Python service has a self-contained multi-stage Containerfile,
so no manual build ordering is needed.
Includes per-service timing to identify bottlenecks.
"""

import subprocess
import time

from common import (
    ensure_initialized,
    fmt_duration,
    print_header,
    print_step,
    print_success,
    print_warning,
)
from compose import compose

# Default services (no profile needed)
SERVICES = ["database", "controller"]

# Managed-profile services (require --profile managed to be visible)
MANAGED_SERVICES = ["recorder"]


def _check_dangling_images() -> None:
    """Warn about dangling (<none>) images without auto-pruning.

    Auto-pruning would destroy intermediate builder layers that
    Podman/Buildah uses for its build cache — so we only warn here.
    """
    binary = "podman"

    result = subprocess.run(
        [binary, "images", "--filter", "dangling=true", "-q"],
        capture_output=True,
        text=True,
    )
    dangling = [line for line in result.stdout.strip().splitlines() if line.strip()]
    if len(dangling) > 20:
        print_warning(
            f"{len(dangling)} dangling images found. "
            "Run 'podman image prune -f' to reclaim disk space."
        )


def main() -> None:
    """Build all images via compose with per-service timing."""
    ensure_initialized()
    print_header("Building Silvasonic Container Images")

    timings: list[tuple[str, float]] = []
    total_start = time.monotonic()

    for service in SERVICES:
        print_step(f"Building {service}...")
        start = time.monotonic()
        compose("build", service)
        elapsed = time.monotonic() - start
        timings.append((service, elapsed))

    # Build managed-profile services (e.g. recorder template)
    for service in MANAGED_SERVICES:
        print_step(f"Building {service} (managed profile)...")
        start = time.monotonic()
        compose("--profile", "managed", "build", service)
        elapsed = time.monotonic() - start
        timings.append((service, elapsed))

    total_elapsed = time.monotonic() - total_start

    # --- Timing Report ---
    print()
    print_step("Build Timing Report")
    max_name = max(len(name) for name, _ in timings)
    max_duration = max(duration for _, duration in timings) if timings else 1.0
    for name, duration in timings:
        bar_len = int(min(duration / max_duration, 1.0) * 30) if max_duration > 0 else 0
        bar = "█" * bar_len + "░" * (30 - bar_len)
        print(f"  {name:<{max_name}}  {bar}  {fmt_duration(duration)}")

    print(f"\n  {'TOTAL':<{max_name}}  {'─' * 30}  {fmt_duration(total_elapsed)}")

    # Check for dangling images (warn only, don't auto-prune)
    _check_dangling_images()

    print_success("All images built! 🎉")


if __name__ == "__main__":
    main()
