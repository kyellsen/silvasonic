"""Fixtures for Recorder integration tests.

Provides a pre-configured ``RecorderService`` connected to a real Redis
container for lifecycle testing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from silvasonic.core.service import SilvaService
from silvasonic.test_utils.helpers import build_redis_url
from testcontainers.redis import RedisContainer

if TYPE_CHECKING:
    from silvasonic.recorder.__main__ import RecorderService


@pytest.fixture
async def recorder_service(
    redis_container: RedisContainer, request: pytest.FixtureRequest
) -> AsyncIterator[RecorderService]:
    """Create, setup, and teardown a RecorderService with real Redis.

    Uses the test node name as ``instance_id`` for automatic uniqueness.
    """
    from silvasonic.recorder.__main__ import RecorderService

    url = build_redis_url(redis_container)
    instance_id = request.node.name  # unique per test

    svc = RecorderService.__new__(RecorderService)
    SilvaService.__init__(svc, redis_url=url, instance_id=instance_id, heartbeat_interval=0.5)

    with patch("silvasonic.core.service_context.start_health_server"):
        await svc._setup()

    yield svc

    await svc._teardown()
