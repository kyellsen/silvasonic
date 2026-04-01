"""Fixtures for Recorder integration tests.

Provides a pre-configured ``RecorderService`` connected to a real Redis
container for lifecycle testing.

Also exports ``skip_no_ffmpeg`` — a shared ``skipif`` marker used by
all integration tests that require a working FFmpeg binary.
"""

from __future__ import annotations

import subprocess
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


# ---------------------------------------------------------------------------
# Shared FFmpeg availability check (DRY — used by all integration tests)
# ---------------------------------------------------------------------------
def _ffmpeg_available() -> bool:
    """Check if FFmpeg is available on the system."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


skip_no_ffmpeg = pytest.mark.skipif(
    not _ffmpeg_available(),
    reason="FFmpeg not installed — skip integration tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
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
