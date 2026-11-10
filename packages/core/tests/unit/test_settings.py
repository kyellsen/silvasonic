"""Unit tests for silvasonic.core.settings module."""

from pathlib import Path

import pytest
from silvasonic.core.settings import DEFAULT_DB_PATH, DatabaseSettings


@pytest.mark.unit
class TestDatabaseSettings:
    """Tests for DatabaseSettings Pydantic model."""

    def test_default_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without an override the database lives in the shared mount."""
        monkeypatch.delenv("SILVASONIC_DB_PATH", raising=False)
        assert DatabaseSettings().SILVASONIC_DB_PATH == DEFAULT_DB_PATH
        assert Path("/data/database/silvasonic.db") == DEFAULT_DB_PATH

    def test_database_url_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """database_url names the aiosqlite driver and the file."""
        monkeypatch.delenv("SILVASONIC_DB_PATH", raising=False)
        assert DatabaseSettings().database_url == "sqlite+aiosqlite:////data/database/silvasonic.db"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """SILVASONIC_DB_PATH moves the file, e.g. for tests and scripts."""
        target = tmp_path / "station.db"
        monkeypatch.setenv("SILVASONIC_DB_PATH", str(target))
        s = DatabaseSettings()
        assert target == s.SILVASONIC_DB_PATH
        assert s.database_url == f"sqlite+aiosqlite:///{target}"
