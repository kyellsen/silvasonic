import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

import structlog
from silvasonic.core.redis.publisher import RedisPublisher

logger = structlog.get_logger()


async def main() -> None:
    """Send a reload command to all services."""
    publisher = RedisPublisher(service_name="verification_script", instance_id="script")

    logger.info("sending_reload_command")

    await publisher.publish_control(
        command="reload_config",
        initiator="verification_script",
        target_service="*",  # Target all services
        target_instance="*",
    )

    logger.info("command_sent", message="Check service logs for receipt")


if __name__ == "__main__":
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
    asyncio.run(main())
