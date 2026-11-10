"""Integration tests for web-mock database connectivity.

Uses the shared ``station_db`` fixture from ``silvasonic-test-utils``
(via root ``conftest.py``) for a real station database file.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from silvasonic.core.database.session import create_station_engine
from silvasonic.web_mock.__main__ import app


@pytest.mark.integration
class TestWebMockDatabaseConnectivity:
    """Verify that web-mock can connect and read/write to the database."""

    @pytest.fixture(autouse=True)
    async def setup_env(
        self, monkeypatch: pytest.MonkeyPatch, station_db: Path
    ) -> AsyncIterator[None]:
        """Point the app at the test database.

        Also clears any dependency_overrides that unit tests may have set on
        the shared ``app`` singleton (e.g. mock get_db), so integration tests
        use real database sessions.
        """
        from silvasonic.core.database.session import override_engine, reset_engine

        # Remove any leftover dependency overrides from unit tests
        app.dependency_overrides.clear()

        engine = create_station_engine(station_db)
        override_engine(engine)

        try:
            yield
        finally:
            reset_engine()
            await engine.dispose()

    async def test_read_write_db(self) -> None:
        """Test writing to the DB via /api/test-db and reading it back."""
        payload = {"section": "test_integration_section", "value": {"hello": "world"}}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/test-db", json=payload)

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["section"] == "test_integration_section"
            assert data["value"] == {"hello": "world"}

    async def test_save_general_settings(self) -> None:
        """Test the HTML form submission endpoint for saving station name."""
        form_data = {"name": "My-Awesome-Station-007"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Send POST request
            response = await client.post(
                "/settings/general", data=form_data, follow_redirects=False
            )

            assert response.status_code == 303
            assert response.headers["location"] == "/settings"

            # Verify it actually changed it in the DB by hitting the dashboard
            response_dash = await client.get("/")
            assert response_dash.status_code == 200
            assert "My-Awesome-Station-007" in response_dash.text
