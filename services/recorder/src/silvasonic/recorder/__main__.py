"""Entry point for `python -m silvasonic.recorder`."""

import signal
import threading

from silvasonic.core.health import start_health_server
from silvasonic.core.logging import configure_logging


def main() -> None:
    """Start the recorder service."""
    configure_logging("recorder")
    start_health_server()  # Uses default health port 9500

    # Placeholder — will be replaced with the actual recording loop.
    # Block the main thread until SIGTERM / SIGINT.
    shutdown = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: shutdown.set())
    signal.signal(signal.SIGINT, lambda _signum, _frame: shutdown.set())
    shutdown.wait()


if __name__ == "__main__":
    main()
