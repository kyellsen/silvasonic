#!/usr/bin/env python3
from common import print_header, print_success, run_command


def main() -> None:
    """Stop the Silvasonic stack."""
    print_header("Stopping Silvasonic Stack...")
    run_command(["podman-compose", "down"])
    print_success("Stack stopped.")


if __name__ == "__main__":
    main()
