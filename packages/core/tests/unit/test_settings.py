"""Unit tests for silvasonic.core.settings module."""

import pytest
from silvasonic.core.settings import DatabaseSettings


@pytest.mark.unit
class TestDatabaseSettings:
    """Tests for DatabaseSettings Pydantic model."""

    def test_default_values(self) -> None:
        """All defaults match expected development values."""
        s = DatabaseSettings()
        assert s.POSTGRES_USER == "silvasonic"
        assert s.POSTGRES_PASSWORD == "silvasonic"
        assert s.POSTGRES_DB == "silvasonic"
        assert s.POSTGRES_HOST == "localhost"
        assert s.POSTGRES_PORT == 5432

    def test_database_url_format(self) -> None:
        """database_url property builds a correct asyncpg connection string."""
        s = DatabaseSettings()
        url = s.database_url
        assert url.startswith("postgresql+asyncpg://")
        assert "silvasonic:silvasonic@localhost:5432/silvasonic" in url

    def test_override_values(self) -> None:
        """Constructor overrides are reflected in database_url."""
        s = DatabaseSettings(
            POSTGRES_USER="admin",
            POSTGRES_PASSWORD="secret",
            POSTGRES_HOST="db.example.com",
            POSTGRES_PORT=5433,
            POSTGRES_DB="production",
        )
        url = s.database_url
        assert "admin:secret@db.example.com:5433/production" in url
