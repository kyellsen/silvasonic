"""Unit tests for silvasonic-controller service."""

import pytest


@pytest.mark.unit
class TestControllerPackage:
    """Basic package and import tests."""

    def test_package_importable(self) -> None:
        """Controller package is importable."""
        import silvasonic.controller

        assert silvasonic.controller is not None

    def test_main_callable(self) -> None:
        """Controller entry point main() is callable."""
        from silvasonic.controller.__main__ import main

        assert callable(main)

    def test_health_server_importable(self) -> None:
        """Health server is importable from core."""
        from silvasonic.core.health import start_health_server

        assert callable(start_health_server)
