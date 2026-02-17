#!/usr/bin/env python3
"""Show the status of all Silvasonic services via compose ps.

Usage:
    python3 scripts/status.py
"""

from common import print_header
from compose import compose


def main() -> None:
    """Show running services."""
    print_header("Silvasonic Service Status")
    compose("ps", "-a", check=False)


if __name__ == "__main__":
    main()
