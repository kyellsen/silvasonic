#!/usr/bin/env python3
"""Stop all Silvasonic services via compose."""

from common import print_header, print_success
from compose import compose


def main() -> None:
    """Stop all Silvasonic services."""
    print_header("Stopping Silvasonic Services")
    compose("down")
    print_success("All Silvasonic services stopped.")


if __name__ == "__main__":
    main()
