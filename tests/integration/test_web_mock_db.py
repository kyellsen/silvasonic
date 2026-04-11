"""Integration tests for web-mock database connectivity.

Uses the shared ``postgres_container`` fixture from ``silvasonic-test-utils``
(via root ``conftest.py``) to spin up a real TimescaleDB instance.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from silvasonic.web_mock.__main__ import app


@pytest.mark.integration
class TestWebMockDatabaseConnectivity:
    """Verify that web-mock can connect and read/write to the database."""

    @pytest.fixture(autouse=True)
    async def setup_env(
        self, monkeypatch: pytest.MonkeyPatch, postgres_container: Any
    ) -> AsyncIterator[None]:
        """Inject the testcontainer's database credentials into the environment.

        Also clears any dependency_overrides that unit tests may have set on
        the shared ``app`` singleton (e.g. mock get_db), so integration tests
        use real database sessions.
        """
        from silvasonic.core.database.session import override_engine, reset_engine
        from silvasonic.test_utils.helpers import build_postgres_url
        from sqlalchemy.ext.asyncio import create_async_engine

        # Remove any leftover dependency overrides from unit tests
        app.dependency_overrides.clear()

        engine = create_async_engine(build_postgres_url(postgres_container))
        override_engine(engine)

        try:
            yield
        finally:
            reset_engine()
            await engine.dispose()

    async def test_read_write_db(self) -> None:
        """Test writing to the DB via /api/test-db and reading it back."""
        payload = {"key": "test_integration_key", "value": {"hello": "world"}}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/test-db", json=payload)

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["key"] == "test_integration_key"
            assert data["value"] == {"hello": "world"}

    async def test_save_general_settings(self) -> None:
        """Test the HTML form submission endpoint for saving station name."""
        form_data = {"station_name": "My-Awesome-Station-007"}

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
