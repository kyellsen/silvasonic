from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.redis.client import get_redis_client
from silvasonic.core.redis.settings import RedisSettings


@pytest.fixture
def mock_redis() -> Generator[MagicMock, None, None]:
    """Mock Redis client fixture."""
    with patch("redis.asyncio.Redis.from_url") as mock:
        yield mock


def test_redis_settings_default() -> None:
    """Test default Redis settings."""
    settings = RedisSettings()
    assert settings.redis_host == "redis"
    assert settings.redis_port == 6379
    assert settings.redis_db == 0
    assert settings.redis_password is None
    assert settings.redis_url == "redis://redis:6379/0"


def test_redis_settings_custom() -> None:
    """Test custom Redis settings."""
    settings = RedisSettings(
        redis_host="localhost", redis_port=6380, redis_db=1, redis_password="secret"
    )
    assert settings.redis_url == "redis://:secret@localhost:6380/1"


@pytest.mark.asyncio
async def test_get_redis_client_connection(mock_redis: MagicMock) -> None:
    """Test get_redis_client context manager."""
    # Setup mock
    mock_client_instance = AsyncMock()
    mock_redis.return_value = mock_client_instance

    # Use context manager
    async with get_redis_client() as client:
        assert client == mock_client_instance

    # Verify connection and cleanup
    mock_redis.assert_called_once()
    mock_client_instance.aclose.assert_called_once()
