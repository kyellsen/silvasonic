"""Minimal health-check HTTP server for Silvasonic services.

Runs in a background daemon thread so the main service loop
is not blocked.  Uses only the standard library — no frameworks needed.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


class HealthMonitor:
    """Thread-safe singleton to track health of service components."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls) -> "HealthMonitor":
        """Ensure singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._components = {}  # type: ignore
        return cls._instance

    def update_status(self, component: str, is_healthy: bool, details: str = "") -> None:
        """Update the health status of a component."""
        with self._lock:
            # Type ignore because _components is initialized in __new__
            self._components[component] = {  # type: ignore
                "healthy": is_healthy,
                "details": details,
            }

    def get_status(self) -> dict[str, Any]:
        """Get the current health status of all monitored components."""
        with self._lock:
            # Type ignore because _components is initialized in __new__
            components = self._components.copy()  # type: ignore

        # Overall status is healthy only if ALL components are healthy
        all_healthy = all(c["healthy"] for c in components.values())

        return {"status": "ok" if all_healthy else "error", "components": components}


class _HealthHandler(BaseHTTPRequestHandler):
    """Respond to GET /healthy with 200 OK (if healthy) or 503 (if not)."""

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == "/healthy":
            status = HealthMonitor().get_status()

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


def start_health_server(port: int = 9500) -> None:
    """Start the health HTTP server on a daemon thread.

    Args:
        port: TCP port to listen on (default 9500).
    """
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
