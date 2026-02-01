from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# We need to import app after patching, or patch where it is used.
# Since app is already created in main.py, patching settings there might affect the lifespan closure if it captures it,
# but main.py imports settings and uses it in lifespan.
from silvasonic.status_board.main import app


def test_root_redirect() -> None:
    """Test that the root URL redirects to /workspace."""
    client = TestClient(app)
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/workspace"


def test_lifespan_startup_success() -> None:
    """Test successful application startup."""
    with patch("silvasonic.status_board.main.settings") as mock_settings:
        mock_settings.DEV_MODE = True
        mock_settings.PORT = 8000
        with TestClient(app):
            # Context manager triggers startup
            pass


def test_lifespan_startup_failure() -> None:
    """Test application startup failure when configuration is invalid."""
    with patch("silvasonic.status_board.main.settings") as mock_settings:
        mock_settings.DEV_MODE = False

        # Mock sys.exit to prevent actual exit and just raise a test-friendly exception
        with patch("sys.exit", side_effect=RuntimeError("Exit Called")) as mock_exit:
            with pytest.raises(RuntimeError, match="Exit Called"):
                with TestClient(app):
                    pass

            mock_exit.assert_called_with(1)
