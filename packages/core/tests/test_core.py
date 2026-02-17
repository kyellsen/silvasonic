"""Minimal unit tests for silvasonic-core package."""

import pytest


@pytest.mark.unit
def test_version_exists() -> None:
    """Core package exposes a version string."""
    from silvasonic.core import __version__

    assert isinstance(__version__, str)
    assert len(__version__) > 0


@pytest.mark.unit
def test_configure_logging_callable() -> None:
    """configure_logging is importable and callable."""
    from silvasonic.core.logging import configure_logging

    assert callable(configure_logging)


@pytest.mark.unit
def test_health_server_callable() -> None:
    """start_health_server is importable and callable."""
    from silvasonic.core.health import start_health_server

    assert callable(start_health_server)
