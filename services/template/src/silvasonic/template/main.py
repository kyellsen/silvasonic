"""Main entry point for the template service."""

import sys


def hello_world() -> str:
    """Return a friendly greeting."""
    return "Hello from Silvasonic Template Service!"


def main() -> None:
    """Execute the main service logic."""
    print(hello_world())
    sys.exit(0)


if __name__ == "__main__":
    main()
