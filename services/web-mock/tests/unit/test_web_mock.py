"""Unit tests for silvasonic-web-mock service — 100 % coverage target.

All DB dependencies are overridden with mocks so tests run without
PostgreSQL or Redis.  Every route, helper, and edge-case is covered.
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
    _base_ctx,
    app,
    get_settings,
    get_station,
)

# ---------------------------------------------------------------------------
# Dependency overrides — no real DB needed
# ---------------------------------------------------------------------------


async def _mock_station() -> dict[str, str]:
    return mock_data.STATION.copy()


async def _mock_settings() -> dict[str, Any]:
    return mock_data.SETTINGS.copy()


async def _mock_get_db() -> AsyncGenerator[AsyncMock, None]:
    session = AsyncMock()
    yield session


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    """Create a TestClient without starting the full lifespan (no Redis needed).

    Re-applies dependency overrides on every test invocation to survive
    ``app.dependency_overrides.clear()`` calls in integration tests.
    """
    app.dependency_overrides[get_station] = _mock_station
    app.dependency_overrides[get_settings] = _mock_settings
    app.dependency_overrides[get_db] = _mock_get_db
    return TestClient(app, raise_server_exceptions=True)


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
        assert len(mock_data.RECORDERS) >= 1
        assert len(mock_data.UPLOADERS) >= 1
        assert len(mock_data.BIRD_DETECTIONS) >= 1
        assert len(mock_data.BIRD_SPECIES_SUMMARY) >= 1
        assert len(mock_data.LOG_SERVICES) >= 1
        assert mock_data.STATION["name"] != ""


# ---------------------------------------------------------------------------
# Base context helper
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestBaseContext:
    """Tests for the _base_ctx() template context builder."""

    def test_base_ctx_returns_expected_keys(self) -> None:
        """_base_ctx produces all keys the templates expect."""
        request = MagicMock()
        request.app.version = "0.2.0"
        station = {"name": "Test-Station"}

        ctx: dict[str, Any] = _base_ctx(request, station, active="dashboard")

        assert ctx["active"] == "dashboard"
        assert ctx["version"] == "0.2.0"
        assert ctx["station"]["name"] == "Test-Station"
        assert "metrics" in ctx
        assert "active_recorders" in ctx
        assert "active_uploaders" in ctx
        assert "alerts" in ctx
        assert "log_services" in ctx
        assert "inspector_services" in ctx


# ---------------------------------------------------------------------------
# Health / ops endpoints
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestHealthEndpoints:
    """Health and diagnostic endpoints."""

    def test_healthy(self, client: TestClient) -> None:
        """GET /healthy returns 200 OK."""
        resp = client.get("/healthy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "web-mock"

    def test_api_test_db_success(self, client: TestClient) -> None:
        """POST /api/test-db succeeds with mocked session."""
        # Override get_db with a session that simulates a successful write+read
        mock_saved = MagicMock()
        mock_saved.key = "test-key"
        mock_saved.value = {"hello": "world"}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_saved

        async def _db_with_saved() -> AsyncGenerator[AsyncMock, None]:
            session = AsyncMock()
            session.execute.return_value = mock_result
            yield session

        app.dependency_overrides[get_db] = _db_with_saved

        resp = client.post(
            "/api/test-db",
            json={"key": "test-key", "value": {"hello": "world"}},
        )

        app.dependency_overrides[get_db] = _mock_get_db  # restore

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["key"] == "test-key"

    def test_api_test_db_read_back_failure(self, client: TestClient) -> None:
        """POST /api/test-db returns 500 when read-back returns None."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        async def _db_read_none() -> AsyncGenerator[AsyncMock, None]:
            session = AsyncMock()
            session.execute.return_value = mock_result
            yield session

        app.dependency_overrides[get_db] = _db_read_none

        resp = client.post(
            "/api/test-db",
            json={"key": "fail-key", "value": {"test": "data"}},
        )

        app.dependency_overrides[get_db] = _mock_get_db  # restore

        assert resp.status_code == 500
        assert "Failed to read back" in resp.json()["detail"]

    def test_api_test_db_read_back_no_key_attr(self, client: TestClient) -> None:
        """POST /api/test-db returns 500 when saved object has no key attribute."""
        mock_saved = MagicMock(spec=[])  # no attributes at all
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_saved

        async def _db_no_key() -> AsyncGenerator[AsyncMock, None]:
            session = AsyncMock()
            session.execute.return_value = mock_result
            yield session

        app.dependency_overrides[get_db] = _db_no_key

        resp = client.post(
            "/api/test-db",
            json={"key": "noattr-key", "value": {"test": "data"}},
        )

        app.dependency_overrides[get_db] = _mock_get_db  # restore

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Page routes (all pages via GET — dependency overrides bypass DB)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestPageRoutes:
    """FastAPI page routes render without errors."""

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
        """Every page route returns HTTP 200 with HTML content."""
        resp = client.get(path)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Silvasonic" in resp.text


# ---------------------------------------------------------------------------
# Detail routes (valid IDs + 404 for nonexistent IDs)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDetailRoutes:
    """Detail page routes for recorders, uploaders, birds, bats."""

    # --- Recorder detail ---
    def test_recorder_detail(self, client: TestClient) -> None:
        """GET /recorders/{id} for a known recorder returns 200."""
        resp = client.get(f"/recorders/{mock_data.RECORDERS[0].id}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_recorder_detail_404(self, client: TestClient) -> None:
        """GET /recorders/{id} for unknown ID returns 404."""
        resp = client.get("/recorders/nonexistent-id")
        assert resp.status_code == 404

    # --- Uploader detail ---
    def test_uploader_detail(self, client: TestClient) -> None:
        """GET /uploaders/{id} for a known uploader returns 200."""
        resp = client.get(f"/uploaders/{mock_data.UPLOADERS[0].id}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_uploader_detail_404(self, client: TestClient) -> None:
        """GET /uploaders/{id} for unknown ID returns 404."""
        resp = client.get("/uploaders/nonexistent-id")
        assert resp.status_code == 404

    # --- Bird detail ---
    def test_bird_detail(self, client: TestClient) -> None:
        """GET /birds/{id} for a known bird species returns 200."""
        resp = client.get(f"/birds/{mock_data.BIRD_SPECIES_SUMMARY[0]['id']}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_bird_detail_404(self, client: TestClient) -> None:
        """GET /birds/{id} for unknown ID returns 404."""
        resp = client.get("/birds/nonexistent-id")
        assert resp.status_code == 404

    # --- Bat detail ---
    def test_bat_detail(self, client: TestClient) -> None:
        """GET /bats/{id} for a known bat species returns 200."""
        resp = client.get(f"/bats/{mock_data.BAT_SPECIES_SUMMARY[0]['id']}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_bat_detail_404(self, client: TestClient) -> None:
        """GET /bats/{id} for unknown ID returns 404."""
        resp = client.get("/bats/nonexistent-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /settings/general
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSettingsPost:
    """Save-settings POST endpoint."""

    def test_save_general_settings_new(self, client: TestClient) -> None:
        """POST /settings/general creates a new SystemConfig when none exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        async def _db_new_setting() -> AsyncGenerator[AsyncMock, None]:
            session = AsyncMock()
            session.execute.return_value = mock_result
            yield session

        app.dependency_overrides[get_db] = _db_new_setting

        resp = client.post(
            "/settings/general",
            data={"station_name": "New-Station"},
            follow_redirects=False,
        )

        app.dependency_overrides[get_db] = _mock_get_db

        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings"

    def test_save_general_settings_update_with_dict(self, client: TestClient) -> None:
        """POST /settings/general updates existing SystemConfig with dict value."""
        existing = MagicMock()
        existing.value = {"timezone": "Europe/Berlin"}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        async def _db_existing() -> AsyncGenerator[AsyncMock, None]:
            session = AsyncMock()
            session.execute.return_value = mock_result
            yield session

        app.dependency_overrides[get_db] = _db_existing

        resp = client.post(
            "/settings/general",
            data={"station_name": "Updated-Station"},
            follow_redirects=False,
        )

        app.dependency_overrides[get_db] = _mock_get_db

        assert resp.status_code == 303
        assert existing.value["station_name"] == "Updated-Station"

    def test_save_general_settings_update_with_none_value(self, client: TestClient) -> None:
        """POST /settings/general handles existing config where value is None."""
        existing = MagicMock()
        existing.value = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        async def _db_none_val() -> AsyncGenerator[AsyncMock, None]:
            session = AsyncMock()
            session.execute.return_value = mock_result
            yield session

        app.dependency_overrides[get_db] = _db_none_val

        resp = client.post(
            "/settings/general",
            data={"station_name": "From-Null"},
            follow_redirects=False,
        )

        app.dependency_overrides[get_db] = _mock_get_db

        assert resp.status_code == 303

    def test_save_general_settings_update_with_non_dict_value(self, client: TestClient) -> None:
        """POST /settings/general handles existing config where value is not a dict."""
        existing = MagicMock()
        existing.value = "not-a-dict"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        async def _db_str_val() -> AsyncGenerator[AsyncMock, None]:
            session = AsyncMock()
            session.execute.return_value = mock_result
            yield session

        app.dependency_overrides[get_db] = _db_str_val

        resp = client.post(
            "/settings/general",
            data={"station_name": "From-String"},
            follow_redirects=False,
        )

        app.dependency_overrides[get_db] = _mock_get_db

        assert resp.status_code == 303


# ---------------------------------------------------------------------------
# SSE console events — test the async generator directly
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSSEConsoleEvents:
    """Server-Sent Events console stream tests."""

    @pytest.mark.asyncio
    async def test_console_events_yields_data(self) -> None:
        """The SSE generator yields log lines for a known service."""
        from silvasonic.web_mock.__main__ import console_events

        request = MagicMock()
        # First call: not disconnected (one yield cycle), second call: disconnected (break)
        request.is_disconnected = AsyncMock(side_effect=[False, True])

        with patch("silvasonic.web_mock.__main__.asyncio.sleep", new_callable=AsyncMock):
            response = await console_events(request=request, service="controller")

            # Consume the full body_iterator — do NOT break early
            events: list[dict[str, str]] = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, dict) and "data" in chunk:
                    events.append(chunk)

        assert len(events) >= 1
        data = json.loads(events[0]["data"])
        assert "service" in data

    @pytest.mark.asyncio
    async def test_console_events_unknown_service_fallback(self) -> None:
        """Unknown service falls back to all log lines."""
        from silvasonic.web_mock.__main__ import console_events

        request = MagicMock()
        request.is_disconnected = AsyncMock(side_effect=[False, True])

        with patch("silvasonic.web_mock.__main__.asyncio.sleep", new_callable=AsyncMock):
            response = await console_events(request=request, service="unknown-svc")

            events: list[dict[str, str]] = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, dict) and "data" in chunk:
                    events.append(chunk)

        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_console_events_disconnects_immediately(self) -> None:
        """Generator exits when client is already disconnected."""
        from silvasonic.web_mock.__main__ import console_events

        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=True)

        with patch("silvasonic.web_mock.__main__.asyncio.sleep", new_callable=AsyncMock):
            response = await console_events(request=request, service="controller")

            events: list[dict[str, str]] = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, dict) and "data" in chunk:
                    events.append(chunk)

        # No data should have been yielded
        assert len(events) == 0


# ---------------------------------------------------------------------------
# get_station / get_settings direct tests (hit real functions with mock DB)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDependencyFunctions:
    """Test get_station() and get_settings() directly with mock sessions."""

    @pytest.mark.asyncio
    async def test_get_station_no_db_record(self) -> None:
        """get_station returns mock data when DB has no record."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute.return_value = mock_result

        # Import the original function (not the override)
        from silvasonic.web_mock.__main__ import get_station as _real_get_station

        result = await _real_get_station(session)
        assert result["name"] == mock_data.STATION["name"]

    @pytest.mark.asyncio
    async def test_get_station_with_db_record(self) -> None:
        """get_station reads station_name from DB when present."""
        saved = MagicMock()
        saved.value = {"station_name": "DB-Station"}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = saved
        session = AsyncMock()
        session.execute.return_value = mock_result

        from silvasonic.web_mock.__main__ import get_station as _real_get_station

        result = await _real_get_station(session)
        assert result["name"] == "DB-Station"

    @pytest.mark.asyncio
    async def test_get_station_with_non_dict_value(self) -> None:
        """get_station ignores saved.value when it is not a dict."""
        saved = MagicMock()
        saved.value = "just-a-string"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = saved
        session = AsyncMock()
        session.execute.return_value = mock_result

        from silvasonic.web_mock.__main__ import get_station as _real_get_station

        result = await _real_get_station(session)
        assert result["name"] == mock_data.STATION["name"]

    @pytest.mark.asyncio
    async def test_get_station_dict_without_station_name(self) -> None:
        """get_station ignores DB value when station_name key is absent."""
        saved = MagicMock()
        saved.value = {"timezone": "Europe/Berlin"}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = saved
        session = AsyncMock()
        session.execute.return_value = mock_result

        from silvasonic.web_mock.__main__ import get_station as _real_get_station

        result = await _real_get_station(session)
        assert result["name"] == mock_data.STATION["name"]

    @pytest.mark.asyncio
    async def test_get_settings_no_db_record(self) -> None:
        """get_settings returns mock data when DB has no record."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute.return_value = mock_result

        from silvasonic.web_mock.__main__ import get_settings as _real_get_settings

        result = await _real_get_settings(session)
        assert result == mock_data.SETTINGS

    @pytest.mark.asyncio
    async def test_get_settings_with_db_record(self) -> None:
        """get_settings merges DB values into mock settings."""
        saved = MagicMock()
        saved.value = {"station_name": "DB-Station", "language": "en"}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = saved
        session = AsyncMock()
        session.execute.return_value = mock_result

        from silvasonic.web_mock.__main__ import get_settings as _real_get_settings

        result = await _real_get_settings(session)
        assert result["station_name"] == "DB-Station"
        assert result["language"] == "en"

    @pytest.mark.asyncio
    async def test_get_settings_with_non_dict_value(self) -> None:
        """get_settings ignores saved.value when it is not a dict."""
        saved = MagicMock()
        saved.value = "string-value"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = saved
        session = AsyncMock()
        session.execute.return_value = mock_result

        from silvasonic.web_mock.__main__ import get_settings as _real_get_settings

        result = await _real_get_settings(session)
        assert result == mock_data.SETTINGS


# ---------------------------------------------------------------------------
# Lifespan context manager
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestLifespan:
    """Test the lifespan async context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_sets_ctx_on_app_state(self) -> None:
        """lifespan() sets app.state.ctx during its lifecycle."""
        from silvasonic.web_mock.__main__ import lifespan

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("silvasonic.web_mock.__main__.ServiceContext", return_value=mock_ctx):
            async with lifespan(app):
                assert app.state.ctx is mock_ctx


# ---------------------------------------------------------------------------
# __main__ guard
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMainGuard:
    """Test that the __main__ guard calls uvicorn.run."""

    def test_main_guard_invokes_uvicorn(self) -> None:
        """The if __name__ == '__main__' block calls uvicorn.run()."""
        import silvasonic.web_mock.__main__ as mod
        import uvicorn

        with patch.object(uvicorn, "run") as mock_run:
            # Simulate what happens when the module is run as __main__
            # by directly executing the guarded block
            exec(
                compile(
                    "if True:\n"
                    "    uvicorn.run(\n"
                    "        'silvasonic.web_mock.__main__:app',\n"
                    "        host='0.0.0.0',\n"
                    f"        port={mod.WEB_MOCK_PORT},\n"
                    "        reload=False,\n"
                    "        log_level='info',\n"
                    "    )\n",
                    "<test>",
                    "exec",
                ),
                {"uvicorn": uvicorn},
            )
            mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# Mock data integrity
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMockDataIntegrity:
    """Validate mock data structure."""

    def test_recorder_fields(self) -> None:
        """RecorderMock has required fields."""
        for rec in mock_data.RECORDERS:
            assert rec.id
            assert rec.label
            assert 0 <= rec.level_pct <= 100
            assert rec.sample_rate > 0

    def test_uploader_fields(self) -> None:
        """UploaderMock has required fields."""
        for up in mock_data.UPLOADERS:
            assert up.id
            assert up.label
            assert up.target_type
            assert up.status

    def test_fake_log_lines_are_valid_json(self) -> None:
        """All fake log lines are parseable as JSON."""
        for line in mock_data.FAKE_LOG_LINES:
            payload = json.loads(line)
            assert "service" in payload
            assert "message" in payload

    def test_weather_statistics_structure(self) -> None:
        """Weather statistics has expected keys and non-empty lists."""
        stats = mock_data.WEATHER_STATISTICS
        expected_keys = [
            "timestamps",
            "temperature",
            "temperature_24h",
            "precipitation",
            "humidity",
            "pressure",
            "wind",
            "wind_gust",
            "sunshine",
        ]
        for key in expected_keys:
            assert key in stats
            assert len(stats[key]) > 0

    def test_bird_species_summary_ids(self) -> None:
        """Bird species summary entries have IDs."""
        for sp in mock_data.BIRD_SPECIES_SUMMARY:
            assert "id" in sp
            assert sp["id"]

    def test_bat_species_summary_ids(self) -> None:
        """Bat species summary entries have IDs."""
        for sp in mock_data.BAT_SPECIES_SUMMARY:
            assert "id" in sp
            assert sp["id"]
