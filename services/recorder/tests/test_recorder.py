"""Unit tests for silvasonic-recorder service."""

import pytest


@pytest.mark.unit
class TestRecorderPackage:
    """Basic package and import tests."""

    def test_package_importable(self) -> None:
        """Recorder package is importable."""
        import silvasonic.recorder

        assert silvasonic.recorder is not None

    def test_main_callable(self) -> None:
        """Recorder entry point main() is callable."""
        from silvasonic.recorder.__main__ import main

        assert callable(main)


@pytest.mark.unit
class TestHealthServer:
    """Health server module tests."""

    def test_health_module_importable(self) -> None:
        """Health module is importable from core."""
        from silvasonic.core.health import start_health_server

        assert callable(start_health_server)

    def test_health_handler_responds_200(self) -> None:
        """Health handler responds with 200 on /healthy."""
        import urllib.request

        from silvasonic.core.health import start_health_server

        start_health_server()  # Uses default port 9500

        req = urllib.request.Request("http://127.0.0.1:9500/healthy")
        with urllib.request.urlopen(req, timeout=2) as resp:
            assert resp.status == 200
