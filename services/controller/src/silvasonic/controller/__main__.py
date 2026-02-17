"""Entry point for `python -m silvasonic.controller`."""

import os
import signal
import threading

from silvasonic.core.health import start_health_server
from silvasonic.core.logging import configure_logging

CONTROLLER_HEALTH_PORT = int(os.environ.get("SILVASONIC_CONTROLLER_PORT", "9100"))


def main() -> None:
    """Start the controller service."""
    configure_logging("controller")
    start_health_server(port=CONTROLLER_HEALTH_PORT)

    # Placeholder — will be replaced with actual orchestration logic.
    # Block the main thread until SIGTERM / SIGINT.
    shutdown = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: shutdown.set())
    signal.signal(signal.SIGINT, lambda _signum, _frame: shutdown.set())
    shutdown.wait()


if __name__ == "__main__":
    main()
