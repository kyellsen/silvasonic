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
from silvasonic.recorder.ffmpeg_pipeline import FFmpegConfig
from silvasonic.recorder.settings import RecorderSettings
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
    Initializes the v0.5.0 attributes that RecorderService.__init__() would
    normally set (_cfg, _pipeline_config, _pipeline).
    """
    from silvasonic.recorder.__main__ import RecorderService

    url = build_redis_url(redis_container)
    instance_id = request.node.name  # unique per test

    svc = RecorderService.__new__(RecorderService)
    SilvaService.__init__(svc, redis_url=url, instance_id=instance_id, heartbeat_interval=0.5)

    # v0.5.0: Initialize attributes that RecorderService.__init__() sets
    svc._cfg = RecorderSettings()
    svc._pipeline_config = FFmpegConfig()
    svc._pipeline = None

    with patch("silvasonic.core.service_context.start_health_server"):
        await svc._setup()

    yield svc

    await svc._teardown()
