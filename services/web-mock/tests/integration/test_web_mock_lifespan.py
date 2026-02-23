"""Integration lifespan test for silvasonic-web-mock.

## What makes this an "integration" test (and not a unit test)?

The unit tests mock ALL infrastructure — logging, health server, Redis,
ResourceCollector, everything. These tests run the **real** lifespan:

  ✅ configure_logging()          — real structlog setup
  ✅ start_health_server()        — real thread + HTTP server
  ✅ ResourceCollector            — real psutil call
  🔧 get_redis_connection()       — mocked (Redis is an EXTERNAL service)
  ✅ graceful teardown            — real shutdown sequence

## Why NOT a pure integration test with a real Redis container?

web-mock has no meaningful Redis interaction:
  - Heartbeat publishing is best-effort and produces no observable output
  - All page data comes from mock_data.py
  - No real-time SSE state depends on Redis

Running a Redis testcontainer just to see heartbeat=HeartbeatPublisher (instead
of heartbeat=None) adds 10-15s startup time with zero additional correctness
signal. The best-effort Redis path is fully tested in core integration tests.

## Summary

web-mock lifespan tests are "integration" in that they test real OS/process
interactions but "mock" only the one true external dependency (Redis).
This is the correct tradeoff for a service that is a pure UI shell.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Allow skipping in CI environments that cannot bind ports
_SKIP = os.getenv("SILVASONIC_SKIP_INTEGRATION", "").lower() in ("1", "true", "yes")


@pytest.fixture(scope="module")
def lifespan_client() -> Generator[TestClient, None, None]:
    """App running with real lifespan — Redis mocked (external service).

    Real infrastructure exercised:
      - configure_logging() — real structlog
      - start_health_server() — real HTTP thread
      - ResourceCollector — real psutil
      - ServiceContext teardown — real shutdown

    Redis mocked because:
      - Redis is external; its integration is tested in core tests
      - Best-effort Redis failure path (heartbeat=None) is the correct
        steady-state to validate for web-mock in a no-infra environment
      - Avoids 15s Docker container startup for zero correctness benefit
    """
    from silvasonic.web_mock.__main__ import app

    with (
        patch(
            "silvasonic.core.service_context.get_redis_connection",
            new_callable=AsyncMock,
            return_value=None,  # simulate "Redis unavailable" — heartbeat skipped
        ),
        TestClient(app, raise_server_exceptions=True) as client,
    ):
        yield client


@pytest.mark.integration
@pytest.mark.skipif(_SKIP, reason="SILVASONIC_SKIP_INTEGRATION=1")
class TestWebMockLifespan:
    """Lifespan integration tests — real startup/shutdown, only Redis mocked."""

    def test_health_ready_after_startup(self, lifespan_client: TestClient) -> None:
        """/healthy returns {status: ok} after real lifespan completes."""
        resp = lifespan_client.get("/healthy")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "web-mock"

    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/recorders",
            "/processor",
            "/uploaders",
            "/birds",
            "/bats",
            "/weather",
            "/settings",
            "/about",
        ],
    )
    def test_all_pages_render_200(self, lifespan_client: TestClient, path: str) -> None:
        """All 9 UI routes return HTTP 200 with HTML after real startup."""
        resp = lifespan_client.get(path)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Silvasonic" in resp.text

    def test_unknown_route_returns_404(self, lifespan_client: TestClient) -> None:
        """Unknown routes return 404 (FastAPI default behaviour)."""
        resp = lifespan_client.get("/does-not-exist")
        assert resp.status_code == 404

    def test_api_docs_available(self, lifespan_client: TestClient) -> None:
        """/docs (OpenAPI UI) is available for developer navigation."""
        resp = lifespan_client.get("/docs")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
