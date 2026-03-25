#!/usr/bin/env python3
"""Stop all Silvasonic services via compose."""

import subprocess

from common import print_header, print_step, print_success
from compose import compose


def _stop_managed_recorders() -> None:
    """Stop and remove any Controller-managed recorder containers.

    These containers are created dynamically via podman-py (ADR-0013)
    and are NOT managed by Compose.  They must be removed before
    ``compose down`` can tear down the shared network.

    Uses a **label filter** (``io.silvasonic.owner=controller``) so that
    test containers (owner ``controller-test-*``) are never affected by
    a ``just stop`` command.
    """
    result = subprocess.run(
        [
            "podman",
            "ps",
            "-a",
            "--filter",
            "label=io.silvasonic.owner=controller",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
    )
    names = result.stdout.strip().splitlines()
    if not names or names == [""]:
        return

    print_step(f"Removing {len(names)} managed recorder container(s)...")
    for name in names:
        subprocess.run(
            ["podman", "rm", "-f", name],
            check=False,
            capture_output=True,
        )


def main() -> None:
    """Stop all Silvasonic services."""
    print_header("Stopping Silvasonic Services")
    _stop_managed_recorders()
    compose("down")
    print_success("All Silvasonic services stopped.")


if __name__ == "__main__":
    main()
