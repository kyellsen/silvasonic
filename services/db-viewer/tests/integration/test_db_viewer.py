"""Integration tests for the DB-Viewer API endpoints."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
from silvasonic.core.database import get_db
from silvasonic.db_viewer.__main__ import app
from silvasonic.test_utils.helpers import build_postgres_url, clean_database
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


@pytest.fixture(autouse=True)
async def _clean_db_tables(postgres_container: PostgresContainer) -> AsyncGenerator[None]:
    """Reset application tables after each test for parallel safety."""
    yield
    await clean_database(postgres_container)


@pytest.mark.integration
class TestDBViewerAPI:
    """Tests for the DB Viewer HTML and Export endpoints."""

    @pytest.fixture
    async def db_session_factory(
        self, postgres_container: PostgresContainer
    ) -> AsyncGenerator[Any]:
        """Provide a session factory attached to the test database."""
        pg_url = build_postgres_url(postgres_container)
        engine = create_async_engine(pg_url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield session_factory
        await engine.dispose()

    @pytest.fixture
    async def override_get_db_session(self, db_session_factory: Any) -> AsyncGenerator[None]:
        """Yield an async session for the FastAPI dependency override."""

        async def _override() -> AsyncGenerator[AsyncSession]:
            async with db_session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = _override
        yield
        app.dependency_overrides.clear()

    @pytest.fixture
    async def client(self, override_get_db_session: Any) -> AsyncGenerator[httpx.AsyncClient]:
        """Provide an async test client for the DB Viewer app."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    async def test_table_snippet_renders_data(
        self,
        db_session_factory: Any,
        postgres_container: PostgresContainer,
        client: httpx.AsyncClient,
    ) -> None:
        """Verify the snippet endpoint renders DB data as HTML."""
        # Insert a test row
        async with db_session_factory() as session:
            from sqlalchemy import text

            await session.execute(
                text(
                    "INSERT INTO system_config (key, value) "
                    "VALUES ('test_key', '{\"test\": \"test_value\"}')"
                )
            )
            await session.commit()

        # Fetch snippet
        response = await client.get("/snippets/table/system_config")
        assert response.status_code == 200
        html = response.text
        assert "test_key" in html
        assert "test_value" in html
        assert "<table" in html

    async def test_export_table_csv(
        self,
        db_session_factory: Any,
        postgres_container: PostgresContainer,
        client: httpx.AsyncClient,
    ) -> None:
        """Verify the export endpoint returns CSV data."""
        # Insert a test row
        async with db_session_factory() as session:
            from sqlalchemy import text

            await session.execute(
                text(
                    "INSERT INTO system_config (key, value) "
                    "VALUES ('export_key', '{\"test\": \"export_val\"}')"
                )
            )
            await session.commit()

        # Export table as CSV
        response = await client.get("/export/system_config?fmt=csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        csv_data = response.text

        # Verify CSV contents
        assert "export_key" in csv_data
        assert "export_val" in csv_data
        assert "key" in csv_data

    async def test_export_table_invalid_table(self, client: httpx.AsyncClient) -> None:
        """Verify export endpoint rejects invalid tables."""
        response = await client.get("/export/invalid_table_name?fmt=csv")
        assert response.status_code == 400
