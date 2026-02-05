import structlog
from silvasonic.controller.settings import ControllerSettings
from silvasonic.core.redis.publisher import RedisPublisher

logger = structlog.get_logger()
settings = ControllerSettings()  # type: ignore[call-arg]


class MessageBroker(RedisPublisher):
    """Handles Redis Pub/Sub communication."""

    def __init__(self) -> None:
        """Initialize Redis connection."""
        super().__init__(service_name="controller", instance_id="main")
