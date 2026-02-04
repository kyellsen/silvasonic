import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def set_test_env_vars():
    """Set required environment variables for recorder tests."""
    if "ICECAST_PASSWORD" not in os.environ:
        os.environ["ICECAST_PASSWORD"] = "testing_password"
