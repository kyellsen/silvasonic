"""Unit tests for HealthMonitor and health HTTP server.

Covers status updates, overall health computation, optional components,
liveness watchdog, HTTP handler (200/503/404), and start_health_server.
"""

import time as _time
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock

import pytest
from silvasonic.core.health import HealthMonitor


@pytest.mark.unit
class TestHealthMonitor:
    """Tests for the HealthMonitor (plain class, no singleton)."""

    def test_update_and_get_status(self) -> None:
        """Status is updated and retrievable."""
        hm = HealthMonitor()
        hm.update_status("recording", True, "running")
        status = hm.get_status()

        assert status["status"] == "ok"
        assert "recording" in status["components"]
        assert status["components"]["recording"]["healthy"] is True
        assert status["components"]["recording"]["details"] == "running"

    def test_overall_unhealthy(self) -> None:
        """Overall status is 'error' if any component is unhealthy."""
        hm = HealthMonitor()
        hm.update_status("a", True)
        hm.update_status("b", False, "disk full")
        status = hm.get_status()

        assert status["status"] == "error"

    def test_all_healthy(self) -> None:
        """Overall status is 'ok' if ALL components are healthy."""
        hm = HealthMonitor()
        hm.update_status("a", True)
        hm.update_status("b", True)
        status = hm.get_status()

        assert status["status"] == "ok"

    def test_empty_components(self) -> None:
        """No components → vacuously all healthy."""
        hm = HealthMonitor()
        status = hm.get_status()

        assert status["status"] == "ok"
        assert status["components"] == {}

    def test_optional_unhealthy_does_not_affect_overall(self) -> None:
        """An optional (required=False) unhealthy component keeps status 'ok'."""
        hm = HealthMonitor()
        hm.update_status("main", True, "running")
        hm.update_status("podman", False, "no socket", required=False)
        status = hm.get_status()

        assert status["status"] == "ok"
        assert status["components"]["podman"]["healthy"] is False
        assert status["components"]["podman"]["required"] is False

    def test_required_unhealthy_causes_error(self) -> None:
        """A required (default) unhealthy component causes status 'error'."""
        hm = HealthMonitor()
        hm.update_status("main", True, "running")
        hm.update_status("database", False, "down")
        status = hm.get_status()

        assert status["status"] == "error"
        assert status["components"]["database"]["required"] is True

    def test_optional_component_included_in_output(self) -> None:
        """Optional components appear in the components dict with required=False."""
        hm = HealthMonitor()
        hm.update_status("a", True, "ok")
        hm.update_status("b", False, "unavailable", required=False)
        status = hm.get_status()

        assert "b" in status["components"]
        assert status["components"]["b"]["required"] is False
        assert status["components"]["b"]["healthy"] is False
        # Overall still ok because b is optional
        assert status["status"] == "ok"


@pytest.mark.unit
class TestHealthMonitorLiveness:
    """Tests for the opt-in liveness watchdog in HealthMonitor."""

    def test_liveness_disabled_without_touch(self) -> None:
        """Watchdog is off by default — is_live() always returns True."""
        hm = HealthMonitor()
        assert hm.is_live() is True

    def test_touch_enables_watchdog(self) -> None:
        """First touch() enables the watchdog."""
        hm = HealthMonitor()
        hm.touch()
        assert hm._liveness_enabled is True

    def test_is_live_after_recent_touch(self) -> None:
        """is_live() returns True when touch() was called recently."""
        hm = HealthMonitor()
        hm.touch()
        assert hm.is_live() is True

    def test_is_live_after_timeout(self) -> None:
        """is_live() returns False when timeout has elapsed."""
        hm = HealthMonitor(liveness_timeout=60.0)
        with hm._lock:
            hm._last_touch = _time.monotonic() - 61.0
            hm._liveness_enabled = True
        assert hm.is_live() is False

    def test_get_status_includes_live_key(self) -> None:
        """get_status() dict always contains a 'live' key."""
        hm = HealthMonitor()
        status = hm.get_status()
        assert "live" in status

    def test_get_status_error_when_frozen(self) -> None:
        """Overall status is 'error' if service is frozen."""
        hm = HealthMonitor(liveness_timeout=60.0)
        with hm._lock:
            hm._last_touch = _time.monotonic() - 61.0
            hm._liveness_enabled = True
        status = hm.get_status()
        assert status["status"] == "error"
        assert status["live"] is False


@pytest.mark.unit
class TestHealthHandler:
    """Tests for the _make_handler HTTP request handler factory."""

    def _make_mock_request(self, monitor: HealthMonitor, path: str = "/healthy") -> Any:
        """Create a mock HTTP request dispatched through _make_handler."""
        from silvasonic.core.health import _make_handler

        handler_cls = _make_handler(monitor)
        handler: Any = handler_cls.__new__(handler_cls)
        handler._monitor = monitor
        handler.path = path
        handler.wfile = BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        return handler

    def test_healthy_returns_200(self) -> None:
        """GET /healthy returns 200 when all components are healthy."""
        hm = HealthMonitor()
        hm.update_status("main", True, "ok")

        handler = self._make_mock_request(hm, "/healthy")
        handler.do_GET()

        handler.send_response.assert_called_once_with(200)

    def test_unhealthy_returns_503(self) -> None:
        """GET /healthy returns 503 when a component is unhealthy."""
        hm = HealthMonitor()
        hm.update_status("main", False, "crash")

        handler = self._make_mock_request(hm, "/healthy")
        handler.do_GET()

        handler.send_response.assert_called_once_with(503)

    def test_unknown_path_returns_404(self) -> None:
        """GET /unknown returns 404."""
        hm = HealthMonitor()

        handler = self._make_mock_request(hm, "/unknown")
        handler.do_GET()

        handler.send_response.assert_called_once_with(404)

    def test_log_message_suppressed(self) -> None:
        """log_message does nothing (no crash, suppresses stderr)."""
        from silvasonic.core.health import _make_handler

        handler_cls = _make_handler(HealthMonitor())
        handler = handler_cls.__new__(handler_cls)
        # Must not raise
        handler.log_message("test %s", "arg")


@pytest.mark.unit
class TestStartHealthServer:
    """Test that start_health_server opens a real socket and serves /healthy."""

    def test_server_responds_200_when_healthy(self) -> None:
        """Start on port 0, send GET /healthy, expect 200 + JSON body."""
        import json
        import urllib.request

        from silvasonic.core.health import start_health_server

        monitor = HealthMonitor()
        monitor.update_status("main", True, "ok")

        server = start_health_server(port=0, monitor=monitor)
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/healthy"
            with urllib.request.urlopen(url, timeout=5) as resp:
                assert resp.status == 200
                body = json.loads(resp.read().decode("utf-8"))
                assert body["status"] == "ok"
                assert "components" in body
        finally:
            server.shutdown()

    def test_server_responds_503_when_unhealthy(self) -> None:
        """GET /healthy returns 503 when a component is unhealthy."""
        import json
        import urllib.error
        import urllib.request

        from silvasonic.core.health import start_health_server

        monitor = HealthMonitor()
        monitor.update_status("disk", False, "disk full")

        server = start_health_server(port=0, monitor=monitor)
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/healthy"
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(url, timeout=5)

            assert exc_info.value.code == 503
            body = json.loads(exc_info.value.read().decode("utf-8"))
            assert body["status"] == "error"
        finally:
            server.shutdown()

    def test_server_responds_404_for_unknown_path(self) -> None:
        """GET /unknown returns 404."""
        import urllib.error
        import urllib.request

        from silvasonic.core.health import start_health_server

        monitor = HealthMonitor()
        server = start_health_server(port=0, monitor=monitor)
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/unknown"
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(url, timeout=5)
            assert exc_info.value.code == 404
        finally:
            server.shutdown()

    def test_server_returns_httpserver_instance(self) -> None:
        """start_health_server returns an HTTPServer for cleanup."""
        from http.server import HTTPServer

        from silvasonic.core.health import start_health_server

        monitor = HealthMonitor()
        server = start_health_server(port=0, monitor=monitor)
        try:
            assert isinstance(server, HTTPServer)
        finally:
            server.shutdown()
