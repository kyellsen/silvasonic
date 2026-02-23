"""Minimal health-check HTTP server for Silvasonic services.

Runs in a background daemon thread so the main service loop
is not blocked.  Uses only the standard library — no frameworks needed.

Provides two health primitives:

*   **Component health** — ``update_status()`` tracks named sub-systems
    (e.g. ``recording``, ``disk_space``).  Overall status is ``ok`` only
    when *all* components are healthy.

*   **Liveness watchdog** (opt-in) — the main service loop calls
    ``touch()`` on every iteration.  If ``touch()`` is never called the
    watchdog stays disabled (backward-compatible).  Once enabled, the
    HTTP endpoint returns ``503`` if no ``touch()`` has been received for
    longer than ``liveness_timeout`` seconds — signalling Podman that the
    service is frozen and should be restarted.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


class HealthMonitor:
    """Thread-safe object to track health of service components.

    One instance is created by ``SilvaService`` and passed explicitly to
    ``start_health_server()``.  There is no global singleton — each service
    process owns exactly one ``HealthMonitor`` instance, which makes the
    class straightforward to instantiate and test.

    Args:
        liveness_timeout: Seconds after which a missing ``touch()`` causes
            the liveness check to fail.  Default: 60 s.
    """

    def __init__(self, liveness_timeout: float = 60.0) -> None:
        """Initialize the health monitor."""
        self._lock = threading.Lock()
        self._components: dict[str, Any] = {}
        self._liveness_timeout = liveness_timeout
        self._last_touch: float = 0.0
        self._liveness_enabled: bool = False

    def update_status(self, component: str, is_healthy: bool, details: str = "") -> None:
        """Update the health status of a component."""
        with self._lock:
            self._components[component] = {
                "healthy": is_healthy,
                "details": details,
            }

    def touch(self) -> None:
        """Signal that the main service loop is alive.

        Call this once per main-loop iteration.  The first call enables
        the watchdog; subsequent calls reset the timer.
        """
        with self._lock:
            self._last_touch = time.monotonic()
            self._liveness_enabled = True

    def is_live(self) -> bool:
        """Return ``True`` if the service is considered alive.

        If the watchdog has never been enabled (``touch()`` was never
        called), always returns ``True`` — preserving backward compat
        for services without a main loop (e.g. pure event listeners).
        """
        with self._lock:
            if not self._liveness_enabled:
                return True
            return (time.monotonic() - self._last_touch) < self._liveness_timeout

    def get_status(self) -> dict[str, Any]:
        """Get the current health status of all monitored components."""
        with self._lock:
            components = self._components.copy()

        live = self.is_live()
        all_healthy = all(c["healthy"] for c in components.values())

        return {
            "status": "ok" if (all_healthy and live) else "error",
            "live": live,
            "components": components,
        }


def _make_handler(monitor: HealthMonitor) -> type[BaseHTTPRequestHandler]:
    """Return a request handler class bound to the given ``HealthMonitor``.

    Using a factory instead of a class attribute avoids any global/singleton
    state: the handler closes over the concrete ``monitor`` instance.
    """

    class _HealthHandler(BaseHTTPRequestHandler):
        """Respond to GET /healthy with 200 OK (if healthy) or 503 (if not)."""

        _monitor = monitor

        def do_GET(self) -> None:
            """Handle GET requests."""
            if self.path == "/healthy":
                status = self._monitor.get_status()

                if status["status"] == "ok":
                    self.send_response(200)
                else:
                    self.send_response(503)

                self.send_header("Content-Type", "application/json")
                self.end_headers()

                response_body = json.dumps(status).encode("utf-8")
                self.wfile.write(response_body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            """Suppress default stderr logging (we use structlog)."""

    return _HealthHandler


def start_health_server(port: int, monitor: HealthMonitor) -> HTTPServer:
    """Start the health HTTP server on a daemon thread.

    Args:
        port: TCP port to listen on.
        monitor: The ``HealthMonitor`` instance whose status is served.

    Returns:
        The running ``HTTPServer`` instance.  Callers can invoke
        ``server.shutdown()`` for a clean stop (useful in tests).
    """
    handler_cls = _make_handler(monitor)
    server = HTTPServer(("0.0.0.0", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
