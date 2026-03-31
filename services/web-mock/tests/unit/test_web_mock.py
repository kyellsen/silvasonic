"""Unit tests for silvasonic-web-mock service.

Focuses on user-visible behavior and HTTP contracts rather than implementation details.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from silvasonic.core.database.session import get_db
from silvasonic.web_mock import mock_data
from silvasonic.web_mock.__main__ import (
    app,
    get_settings,
    get_station,
)

# ---------------------------------------------------------------------------
# Dependency overrides
# ---------------------------------------------------------------------------


async def _mock_station() -> dict[str, str]:
    return mock_data.STATION.copy()


async def _mock_settings() -> dict[str, Any]:
    return mock_data.SETTINGS.copy()


async def _mock_get_db() -> AsyncGenerator[AsyncMock]:
    session = AsyncMock(add=MagicMock())
    yield session


@pytest.fixture()
def client() -> TestClient:
    """Create a TestClient with basic DB dependency overrides.

    Re-applies overrides on every test invocation to survive
    ``app.dependency_overrides.clear()`` calls in integration tests.
    """
    app.dependency_overrides[get_station] = _mock_station
    app.dependency_overrides[get_settings] = _mock_settings
    app.dependency_overrides[get_db] = _mock_get_db
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Health / Ops
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestHealthEndpoints:
    """Health and diagnostic endpoints."""

    def test_healthy(self, client: TestClient) -> None:
        """GET /healthy returns 200 OK and expected structure."""
        resp = client.get("/healthy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "web-mock"


# ---------------------------------------------------------------------------
# Page routes (HTML generation)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestPageRoutes:
    """FastAPI page routes render correctly with mocked base data."""

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
            "/livesound",
            "/settings",
            "/about",
        ],
    )
    def test_page_renders_200(self, client: TestClient, path: str) -> None:
        """Core pages return HTTP 200 and contain common layout elements."""
        resp = client.get(path)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

        # Behavior check: Every page should render the base layout and station name
        assert "Silvasonic" in resp.text
        assert mock_data.STATION["name"] in resp.text


# ---------------------------------------------------------------------------
# Detail routes
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDetailRoutes:
    """Detail page routes return meaningful HTML for valid IDs and 404 otherwise."""

    def test_recorder_detail(self, client: TestClient) -> None:
        """Recorder detail page renders basic hardware info."""
        rec = mock_data.RECORDERS[0]
        resp = client.get(f"/recorders/{rec.id}")
        assert resp.status_code == 200
        assert rec.label in resp.text

    def test_recorder_detail_404(self, client: TestClient) -> None:
        """GET /recorders/{id} for unknown ID returns 404."""
        resp = client.get("/recorders/nonexistent-id")
        assert resp.status_code == 404

    def test_uploader_detail(self, client: TestClient) -> None:
        """Uploader detail page renders targeting info."""
        up = mock_data.UPLOADERS[0]
        resp = client.get(f"/uploaders/{up.id}")
        assert resp.status_code == 200
        assert up.label in resp.text
        assert up.target_type in resp.text

    def test_uploader_detail_404(self, client: TestClient) -> None:
        """GET /uploaders/{id} for unknown ID returns 404."""
        resp = client.get("/uploaders/nonexistent-id")
        assert resp.status_code == 404

    def test_bird_detail(self, client: TestClient) -> None:
        """Bird species detail page renders scientific name."""
        bird = mock_data.BIRD_SPECIES_SUMMARY[0]
        resp = client.get(f"/birds/{bird['id']}")
        assert resp.status_code == 200
        assert bird["species_en"] in resp.text

    def test_bird_detail_404(self, client: TestClient) -> None:
        """GET /birds/{id} for unknown ID returns 404."""
        resp = client.get("/birds/nonexistent-id")
        assert resp.status_code == 404

    def test_bat_detail(self, client: TestClient) -> None:
        """Bat species detail page renders scientific name."""
        bat = mock_data.BAT_SPECIES_SUMMARY[0]
        resp = client.get(f"/bats/{bat['id']}")
        assert resp.status_code == 200
        assert bat["species_en"] in resp.text

    def test_bat_detail_404(self, client: TestClient) -> None:
        """GET /bats/{id} for unknown ID returns 404."""
        resp = client.get("/bats/nonexistent-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Form POST behavior
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSettingsBehavior:
    """Settings pages check integration behavior instead of internal helper dicts."""

    def test_persisted_station_name_reflected_in_ui(self, client: TestClient) -> None:
        """Settings page shows the customized station name if provided by DB."""

        # Cleanly override the dependency for this single test to simulate DB load
        async def _custom_station() -> dict[str, str]:
            return {"name": "Customized DB Station"}

        app.dependency_overrides[get_station] = _custom_station

        resp = client.get("/settings")
        assert resp.status_code == 200
        assert "Customized DB Station" in resp.text

        # Restore fixture defaults
        app.dependency_overrides[get_station] = _mock_station

    def test_save_general_settings_success(self, client: TestClient) -> None:
        """POST /settings/general creates/updates settings and redirects."""
        # Override DB properly to emulate success
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        async def _db_new_setting() -> AsyncGenerator[AsyncMock]:
            session = AsyncMock(add=MagicMock())
            session.execute.return_value = mock_result
            yield session

        app.dependency_overrides[get_db] = _db_new_setting

        resp = client.post(
            "/settings/general",
            data={"station_name": "New-Station-Name"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings"

        # Restore mock generic DB
        app.dependency_overrides[get_db] = _mock_get_db


# ---------------------------------------------------------------------------
# SSE Streams
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSSEConsoleEvents:
    """Server-Sent Events behavior for live console streaming."""

    def test_sse_endpoint_contract(self, client: TestClient) -> None:
        """/events/console?service=... returns a valid event-stream with payloads."""
        with patch("starlette.requests.Request.is_disconnected", new_callable=AsyncMock) as m_dis:
            # First iter: not disconnected, second iter: disconnected
            m_dis.side_effect = [False, True]
            with patch("silvasonic.web_mock.__main__.asyncio.sleep", new_callable=AsyncMock):
                response = client.get("/events/console?service=controller")

                assert response.status_code == 200
                assert "text/event-stream" in response.headers["content-type"]

                # Split events
                events = [line for line in response.text.split("\n") if line.startswith("data: ")]
                assert len(events) >= 1

                payload = json.loads(events[0].replace("data: ", "", 1))
                assert "service" in payload
                assert payload["service"] == "controller"

    def test_sse_endpoint_unknown_service_fallback(self, client: TestClient) -> None:
        """Unknown service falls back gracefully and still emits log lines."""
        with patch("starlette.requests.Request.is_disconnected", new_callable=AsyncMock) as m_dis:
            m_dis.side_effect = [False, True]
            with patch("silvasonic.web_mock.__main__.asyncio.sleep", new_callable=AsyncMock):
                response = client.get("/events/console?service=unknown-service-xyz")

                assert response.status_code == 200

                events = [line for line in response.text.split("\n") if line.startswith("data: ")]
                assert len(events) >= 1

                payload = json.loads(events[0].replace("data: ", "", 1))
                assert "service" in payload
                assert "message" in payload
