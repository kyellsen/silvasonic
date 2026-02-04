import asyncio
from collections.abc import Generator

# Allow imports to patch settings
from unittest.mock import patch

import pytest
from silvasonic.core.redis.client import get_redis_client
from silvasonic.core.redis.publisher import RedisPublisher
from silvasonic.core.redis.settings import RedisSettings
from silvasonic.core.redis.subscriber import RedisSubscriber
from silvasonic.core.schemas.control import ControlMessage
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="module")
def redis_container() -> Generator[RedisContainer, None, None]:
    """Spin up Redis container."""
    with RedisContainer("redis:7-alpine") as redis:
        yield redis


@pytest.fixture
def redis_settings(redis_container: RedisContainer) -> RedisSettings:
    """Override settings to point to container."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return RedisSettings(redis_host=host, redis_port=port, redis_db=0)


@pytest.mark.asyncio
async def test_control_stream_delivery(redis_settings: RedisSettings) -> None:
    """Test that control messages are reliably delivered via Streams."""
    # 1. Patch Settings
    # We patch settings in the main block below.
    # The previous empty block with unused mocks was redundant.

    # Re-patching correctly
    with patch("silvasonic.core.redis.client.settings", redis_settings):
        # 2. Setup Subscriber
        received_msgs = []
        ready_event = asyncio.Event()

        async def handler(msg: ControlMessage) -> None:
            received_msgs.append(msg)
            ready_event.set()

        subscriber = RedisSubscriber(service_name="test_service", instance_id="test_1")
        subscriber.register_handler("test_cmd", handler)

        # Start Subscriber (Joins Group)
        await subscriber.start()

        # Allow time for group creation
        await asyncio.sleep(0.5)

        # 3. Setup Publisher & Publish
        publisher = RedisPublisher(service_name="tester", instance_id="main")
        await publisher.publish_control(
            command="test_cmd",
            initiator="test_suite",
            target_service="test_service",
            target_instance="test_1",
            params={"foo": "bar"},
        )

        # 4. Wait for Delivery
        try:
            await asyncio.wait_for(ready_event.wait(), timeout=5.0)
        except TimeoutError:
            pytest.fail("Message not delivered within 5 seconds")

        await subscriber.stop()

        # 5. Assertions
        assert len(received_msgs) == 1
        msg = received_msgs[0]
        assert msg.command == "test_cmd"
        assert msg.payload.params["foo"] == "bar"

        # 6. Verify Stream Persistence
        async with get_redis_client() as redis:
            # Check length is 1
            length = await redis.xlen("stream:control")
            assert length >= 1


@pytest.mark.asyncio
async def test_audit_stream_persistence(redis_settings: RedisSettings) -> None:
    """Test that audit logging persists to stream."""
    with patch("silvasonic.core.redis.client.settings", redis_settings):
        publisher = RedisPublisher(service_name="tester", instance_id="main")

        await publisher.publish_audit("user_login", {"user": "admin"})
        await publisher.publish_audit("file_deleted", {"file": "a.wav"})

        # Verify manually
        async with get_redis_client() as redis:
            # We expect stream:audit to have 2 entries
            data = await redis.xrange("stream:audit")
            assert len(data) == 2

            # Check content
            # data is [(id, fields), ...]
            # fields is {json: string} (due to decode_responses=True)
            last_entry = data[-1]
            fields = last_entry[1]
            assert "json" in fields
            assert "file_deleted" in fields["json"]
