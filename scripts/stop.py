#!/usr/bin/env python3
from common import print_header, print_step, print_success, run_command


def main() -> None:
    """Stop the Silvasonic stack."""
    print_header("Stopping Silvasonic Stack...")

    # 1. Stop Static Services
    print_step("Stopping static services (podman-compose)...")
    run_command(["podman-compose", "down"], check=False)

    # 2. Stop Dynamic Services
    print_step("Stopping dynamic containers...")
    # Find and force-remove all containers managed by the controller
    # xargs -r prevents running the command if input is empty
    cleanup_cmd = (
        "podman ps -aq --filter label=managed_by=silvasonic-controller | xargs -r podman rm -f"
    )
    run_command(cleanup_cmd, shell=True)

    print_success("Stack stopped.")


if __name__ == "__main__":
    main()
