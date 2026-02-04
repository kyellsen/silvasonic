from unittest.mock import AsyncMock, patch

import pytest
import yaml
from silvasonic.controller.bootstrap import ProfileBootstrapper


@pytest.fixture
def mock_session():
    """Fixture for mocking AsyncSessionLocal."""
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = None
    return session


@pytest.mark.asyncio
async def test_sync_dir_not_exists() -> None:
    """Test early return if directory does not exist."""
    with patch("silvasonic.controller.bootstrap.Path") as mock_path:
        mock_path.return_value.exists.return_value = False

        bootstrapper = ProfileBootstrapper("/tmp/fake")
        await bootstrapper.sync()

        # Verify warnings logged? (assuming structlog capture not strictly needed for coverage)


@pytest.mark.asyncio
async def test_sync_no_profiles(tmp_path, mock_session) -> None:
    """Test sync with empty directory."""
    # tmp_path exists but is empty
    with patch("silvasonic.controller.bootstrap.AsyncSessionLocal", return_value=mock_session):
        bootstrapper = ProfileBootstrapper(str(tmp_path))
        await bootstrapper.sync()

        # Session should not be used if no profiles found
        mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_sync_valid_profile(tmp_path, mock_session) -> None:
    """Test sync with a valid YAML profile."""
    # Create a dummy profile
    profile_data = {
        "slug": "test-mic",
        "name": "Test Mic",
        "audio": {"match_pattern": "Test"},
        "description": "A test profile",
    }
    p_file = tmp_path / "profile.yml"
    with open(p_file, "w") as f:
        yaml.dump(profile_data, f)

    with patch("silvasonic.controller.bootstrap.AsyncSessionLocal", return_value=mock_session):
        bootstrapper = ProfileBootstrapper(str(tmp_path))
        await bootstrapper.sync()

        # Verify DB interaction
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_sync_invalid_profile(tmp_path, mock_session) -> None:
    """Test sync with invalid YAML (missing slug)."""
    # Create an invalid profile
    profile_data = {"name": "No Slug"}
    p_file = tmp_path / "invalid.yml"
    with open(p_file, "w") as f:
        yaml.dump(profile_data, f)

    with patch("silvasonic.controller.bootstrap.AsyncSessionLocal", return_value=mock_session):
        bootstrapper = ProfileBootstrapper(str(tmp_path))
        await bootstrapper.sync()

        # Should log warning and skip
        mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_sync_file_read_error(tmp_path, mock_session) -> None:
    """Test handling of file read error."""
    # Create a directory instead of file to trigger read error or mock it
    # Easier to mock open or yaml.safe_load
    p_file = tmp_path / "error.yml"
    p_file.touch()

    with patch("silvasonic.controller.bootstrap.AsyncSessionLocal", return_value=mock_session):
        with patch("builtins.open", side_effect=OSError("Read Error")):
            bootstrapper = ProfileBootstrapper(str(tmp_path))
            await bootstrapper.sync()

            # Should catch exception and log error
            mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_sync_db_error(tmp_path, mock_session) -> None:
    """Test handling of database error."""
    profile_data = {"slug": "test", "name": "Test"}
    p_file = tmp_path / "test.yml"
    with open(p_file, "w") as f:
        yaml.dump(profile_data, f)

    mock_session.execute.side_effect = Exception("DB Boom")

    with patch("silvasonic.controller.bootstrap.AsyncSessionLocal", return_value=mock_session):
        bootstrapper = ProfileBootstrapper(str(tmp_path))
        await bootstrapper.sync()

        mock_session.rollback.assert_called_once()
