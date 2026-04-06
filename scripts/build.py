#!/usr/bin/env python3
"""Build all Silvasonic container images via compose build.

Each Python service has a self-contained multi-stage Containerfile,
so no manual build ordering is needed.
Includes per-service timing to identify bottlenecks.
"""

import subprocess
import sys
import time

from common import (
    ensure_initialized,
    fmt_duration,
    load_env_value,
    print_header,
    print_step,
    print_success,
    print_warning,
)
from compose import compose

# Default services
SERVICES = ["database", "controller", "processor", "web-mock"]

# Managed-profile services (require --profile managed to be visible)
MANAGED_SERVICES = ["recorder", "birdnet"]


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

    target_services = sys.argv[1:]

    if target_services:
        print_header(f"Building Services: {', '.join(target_services)}")
        build_services = target_services
    else:
        print_header("Building Silvasonic Container Images")
        build_services = list(SERVICES)

        # Add db-viewer to SERVICES if enabled
        import os

        env_db_viewer = os.environ.get("SILVASONIC_DB_VIEWER_RUN")
        env_file_db_viewer = load_env_value("SILVASONIC_DB_VIEWER_RUN")
        db_viewer_run = (env_db_viewer or env_file_db_viewer or "true").lower() in (
            "true",
            "1",
            "yes",
        )
        if db_viewer_run:
            build_services.append("db-viewer")

        # Add managed services to the list
        build_services.extend(MANAGED_SERVICES)

    timings: list[tuple[str, float]] = []
    total_start = time.monotonic()

    for service in build_services:
        if service in MANAGED_SERVICES:
            print_step(f"Building {service} (managed profile)...")
            start = time.monotonic()
            compose("--profile", "managed", "build", service)
            elapsed = time.monotonic() - start
        else:
            print_step(f"Building {service}...")
            start = time.monotonic()
            compose("build", service)
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
