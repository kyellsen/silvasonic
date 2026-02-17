"""Minimal health-check HTTP server for Silvasonic services.

Runs in a background daemon thread so the main service loop
is not blocked.  Uses only the standard library — no frameworks needed.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _HealthHandler(BaseHTTPRequestHandler):
    """Respond to GET /healthy with 200 OK."""

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == "/healthy":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
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
