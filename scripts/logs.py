#!/usr/bin/env python3
"""Stream aggregated logs from all Silvasonic services via compose."""

from compose import compose


def main() -> None:
    """Stream logs from all services."""
    compose("logs", "-f", check=False)


if __name__ == "__main__":
    main()
