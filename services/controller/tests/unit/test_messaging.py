import json
from unittest.mock import AsyncMock, patch

import pytest
from silvasonic.controller.messaging import MessageBroker


@pytest.fixture
def broker():
    """Fixture for MessageBroker with mocked redis."""
    with patch("silvasonic.core.redis.client.redis.Redis") as mock_redis_cls:
        # The implementation uses Redis.from_url(), so we need to mock that result
        mock_client = mock_redis_cls.from_url.return_value

        # Configure methods to be awaitable
        mock_client.publish = AsyncMock()
        mock_client.set = AsyncMock()
        mock_client.aclose = AsyncMock()

        mb = MessageBroker()
        # Attach the mock client to the broker for assertions in tests
        mb.redis = mock_client
        yield mb


@pytest.mark.asyncio
async def test_publish_status_success(broker):
    """Test successful status publish."""
    broker.redis.publish = AsyncMock()
    broker.redis.set = AsyncMock()

    await broker.publish_status(
        status="online", activity="testing", message="OK", meta={"foo": "bar"}
    )

    broker.redis.publish.assert_called_once()
    args = broker.redis.publish.call_args[0]
    channel = args[0]
    payload = json.loads(args[1])

    assert channel == "silvasonic.status"
    assert payload["service"] == "controller"
    assert payload["instance_id"] == "main"
    assert payload["payload"]["health"] == "healthy"
    assert payload["payload"]["activity"] == "testing"
    assert payload["payload"]["meta"]["foo"] == "bar"

    broker.redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_publish_status_error(broker):
    """Test handling of redis errors."""
    broker.redis.publish = AsyncMock(side_effect=Exception("Redis Down"))

    # Should not raise exception (logged only)
    await broker.publish_status(status="online", activity="testing", message="OK")
