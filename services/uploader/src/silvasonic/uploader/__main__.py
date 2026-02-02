import time

import structlog

logger = structlog.get_logger()


def main() -> None:
    """Entry point for the uploader service."""
    logger.info("uploader_service_started")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
