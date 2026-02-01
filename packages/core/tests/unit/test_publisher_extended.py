import json
from unittest.mock import AsyncMock, patch

import pytest
from silvasonic.core.redis.publisher import RedisPublisher


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock Redis client."""
    mock = AsyncMock()
    # Mock the context manager behavior of get_redis_client
    mock.__aenter__.return_value = mock
    mock.__aexit__.return_value = None
    return mock


@pytest.mark.asyncio
async def test_publish_control(mock_redis: AsyncMock) -> None:
    """Test publishing a control message."""
    with patch("silvasonic.core.redis.publisher.get_redis_client", return_value=mock_redis):
        publisher = RedisPublisher("test-service", "test-instance")
        await publisher.publish_control(
            command="reload_config",
            initiator="admin",
            target_service="birdnet",
            params={"threshold": 0.8},
        )

        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "silvasonic.control"

        payload = json.loads(args[1])
        assert payload["topic"] == "control"
        assert payload["command"] == "reload_config"
        assert payload["initiator"] == "admin"
        assert payload["target_service"] == "birdnet"
        assert payload["payload"]["params"] == {"threshold": 0.8}


@pytest.mark.asyncio
async def test_publish_audit(mock_redis: AsyncMock) -> None:
    """Test publishing an audit message."""
    with patch("silvasonic.core.redis.publisher.get_redis_client", return_value=mock_redis):
        publisher = RedisPublisher("test-service", "test-instance")
        await publisher.publish_audit(
            event="file_uploaded",
            payload={"filename": "test.wav", "size": 1024},
        )

        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "silvasonic.audit"

        payload = json.loads(args[1])
        assert payload["topic"] == "audit"
        assert payload["event"] == "file_uploaded"
        assert payload["service"] == "test-service"
        assert payload["payload"] == {"filename": "test.wav", "size": 1024}
