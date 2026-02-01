from silvasonic.status_board.config import Settings


def test_config_defaults() -> None:
    """Test that the default configuration settings are correct."""
    s = Settings()
    assert s.POSTGRES_USER == "postgres"
    assert s.POSTGRES_HOST == "database"
    assert "postgresql+asyncpg://" in s.database_url
    assert s.database_url == "postgresql+asyncpg://postgres:password@database:5432/silvasonic"
