"""Smoke tests for the running Silvasonic stack.

These tests verify that all services are alive and responding.
Prerequisites: `make start` must have been run before these tests.
"""

import os
import socket

import httpx
import pytest
from tenacity import retry, retry_if_exception_type, stop_after_delay, wait_fixed


def _get_env(key: str, default: str) -> str:
    """Read from environment or .env file."""
    val = os.environ.get(key)
    if val:
        return val
    env_file = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip()
    except FileNotFoundError:
        pass
    return default


CONTROLLER_PORT = _get_env("SILVASONIC_CONTROLLER_PORT", "9100")
RECORDER_PORT = _get_env("SILVASONIC_RECORDER_PORT", "9500")
DB_PORT = _get_env("SILVASONIC_DB_PORT", "5432")


@pytest.mark.smoke
class TestServiceHealth:
    """Verify all services respond to health probes."""

    @retry(
        stop=stop_after_delay(30),
        wait=wait_fixed(1),
        retry=retry_if_exception_type((AssertionError, httpx.ConnectError, httpx.ReadTimeout)),
        reraise=True,
    )
    def test_controller_healthy(self) -> None:
        """Controller /healthy returns 200."""
        print(f"Probe Controller on port {CONTROLLER_PORT}...")
        url = f"http://localhost:{CONTROLLER_PORT}/healthy"
        # Increased timeout to avoid flakiness during startup
        resp = httpx.get(url, timeout=2.0)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @retry(
        stop=stop_after_delay(30),
        wait=wait_fixed(1),
        retry=retry_if_exception_type((AssertionError, httpx.ConnectError, httpx.ReadTimeout)),
        reraise=True,
    )
    def test_recorder_healthy(self) -> None:
        """Recorder /healthy returns 200."""
        print(f"Probe Recorder on port {RECORDER_PORT}...")
        url = f"http://localhost:{RECORDER_PORT}/healthy"
        resp = httpx.get(url, timeout=2.0)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @retry(
        stop=stop_after_delay(30),
        wait=wait_fixed(1),
        retry=retry_if_exception_type((AssertionError, ConnectionRefusedError, TimeoutError)),
        reraise=True,
    )
    def test_database_healthy(self) -> None:
        """Database accepts TCP connections on configured port."""
        print(f"Probe Database on port {DB_PORT}...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        try:
            result = sock.connect_ex(("localhost", int(DB_PORT)))
            assert result == 0, f"Database not reachable on port {DB_PORT}"
        finally:
            sock.close()
