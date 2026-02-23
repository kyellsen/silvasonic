"""Unit tests for silvasonic-web-mock service — 100 % coverage target."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Package import
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestWebMockPackage:
    """Basic package-level tests."""

    def test_package_importable(self) -> None:
        """Package is importable."""
        import silvasonic.web_mock

        assert silvasonic.web_mock is not None

    def test_mock_data_importable(self) -> None:
        """mock_data module is importable and contains expected attributes."""
        from silvasonic.web_mock import mock_data

        assert len(mock_data.RECORDERS) >= 1
        assert len(mock_data.UPLOADERS) >= 1
        assert len(mock_data.BIRD_DETECTIONS) >= 1
        assert len(mock_data.BIRD_SPECIES_SUMMARY) >= 1
        assert len(mock_data.LOG_SERVICES) >= 1
        assert mock_data.STATION["name"] != ""


# ---------------------------------------------------------------------------
# HTTP routes (via TestClient — no real server, no Redis, no DB)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestWebMockRoutes:
    """FastAPI routes render without errors."""

    @pytest.fixture()
    def client(self) -> TestClient:
        """Create a TestClient without starting the full lifespan (no Redis needed)."""
        from silvasonic.web_mock.__main__ import app

        # Use raise_server_exceptions=True so template errors surface immediately
        return TestClient(app, raise_server_exceptions=True)

    def test_health_endpoint(self, client: TestClient) -> None:
        """GET /healthy returns 200 OK."""
        resp = client.get("/healthy")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

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
    def test_page_renders_200(self, client: TestClient, path: str) -> None:
        """Every page route returns HTTP 200 with HTML content."""
        resp = client.get(path)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Silvasonic" in resp.text


# ---------------------------------------------------------------------------
# Mock data integrity
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMockDataIntegrity:
    """Validate mock data structure."""

    def test_recorder_fields(self) -> None:
        """RecorderMock has required fields."""
        from silvasonic.web_mock.mock_data import RECORDERS

        for rec in RECORDERS:
            assert rec.id
            assert rec.label
            assert 0 <= rec.level_pct <= 100
            assert rec.sample_rate > 0

    def test_fake_log_lines_are_valid_json(self) -> None:
        """All fake log lines are parseable as JSON."""
        import json

        from silvasonic.web_mock.mock_data import FAKE_LOG_LINES

        for line in FAKE_LOG_LINES:
            payload = json.loads(line)
            assert "service" in payload
            assert "message" in payload
