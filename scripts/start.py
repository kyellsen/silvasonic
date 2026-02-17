#!/usr/bin/env python3
"""Start all Silvasonic services in detached mode via compose."""

from common import print_header, print_success
from compose import compose


def main() -> None:
    """Start all Silvasonic services."""
    print_header("Starting Silvasonic Services")
    compose("up", "-d")
    print_success("Silvasonic services are running.")


if __name__ == "__main__":
    main()
