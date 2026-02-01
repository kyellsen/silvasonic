import os
from unittest.mock import AsyncMock, patch

import pytest
from silvasonic.core.database.session import DatabaseSettings, get_db


class TestDatabaseSettings:
    """Tests for the DatabaseSettings configuration class."""

    def test_default_settings(self) -> None:
        """Verify default configuration values."""
        settings = DatabaseSettings()
        assert settings.POSTGRES_USER == "postgres"
        assert settings.POSTGRES_PASSWORD == "password"
        assert settings.POSTGRES_HOST == "database"
        assert settings.POSTGRES_PORT == 5432
        assert settings.POSTGRES_DB == "silvasonic"

        expected_url = "postgresql+asyncpg://postgres:password@database:5432/silvasonic"
        assert settings.database_url == expected_url

    def test_settings_override(self) -> None:
        """Verify environment variables override defaults."""
        os.environ["POSTGRES_USER"] = "testuser"
        os.environ["POSTGRES_HOST"] = "localhost"

        try:
            settings = DatabaseSettings()
            assert settings.POSTGRES_USER == "testuser"
            assert settings.POSTGRES_HOST == "localhost"
            assert "testuser" in settings.database_url
            assert "localhost" in settings.database_url
        finally:
            # Cleanup env vars
            del os.environ["POSTGRES_USER"]
            del os.environ["POSTGRES_HOST"]


@pytest.mark.asyncio
async def test_get_db_yields_session() -> None:
    """Verify get_db dependency yields a session and closes it."""
    # Mock the AsyncSessionLocal factory
    mock_session = AsyncMock()
    # When enter is called (async with ...), return the mock_session itself
    mock_session.__aenter__.return_value = mock_session

    with patch("silvasonic.core.database.session.AsyncSessionLocal") as mock_factory:
        mock_factory.return_value = mock_session

        # Act
        # get_db is a generator, so we iterate over it
        async for session in get_db():
            assert session == mock_session

        # Assert
        # Verify the session factory was called
        mock_factory.assert_called_once()
        # Verify __aenter__ and __aexit__ were called (context manager)
        assert mock_session.__aenter__.called
        assert mock_session.__aexit__.called
