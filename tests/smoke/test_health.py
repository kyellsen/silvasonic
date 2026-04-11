"""Smoke tests — health probes and heartbeat verification for all Silvasonic services.

Each test uses testcontainer fixtures (from conftest.py) to spin up
isolated, ephemeral containers with random ports. No conflicts with
the dev stack, no host-filesystem writes, automatic cleanup.
"""

import json
import socket
import time
from typing import Any

import httpx
import pytest
from redis import Redis
from testcontainers.core.container import DockerContainer


@pytest.mark.smoke
class TestServiceHealth:
    """Verify all services respond to health probes via testcontainers."""

    def test_database_healthy(self, database_container: DockerContainer) -> None:
        """Database accepts TCP connections on its exposed port."""
        host = database_container.get_container_host_ip()
        port = int(database_container.get_exposed_port(5432))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        try:
            result = sock.connect_ex((host, port))
            assert result == 0, f"Database not reachable on {host}:{port}"
        finally:
            sock.close()

    def test_controller_healthy(self, controller_container: DockerContainer) -> None:
        """Controller /healthy returns 200 with status ok."""
        host = controller_container.get_container_host_ip()
        port = int(controller_container.get_exposed_port(9100))
        resp = httpx.get(f"http://{host}:{port}/healthy", timeout=5.0)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_recorder_healthy(self, recorder_container: DockerContainer) -> None:
        """Recorder /healthy returns 200 with status ok."""
        host = recorder_container.get_container_host_ip()
        port = int(recorder_container.get_exposed_port(9500))
        resp = httpx.get(f"http://{host}:{port}/healthy", timeout=5.0)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_processor_healthy(self, processor_container: DockerContainer) -> None:
        """Processor /healthy returns 200 with status ok."""
        host = processor_container.get_container_host_ip()
        port = int(processor_container.get_exposed_port(9200))
        resp = httpx.get(f"http://{host}:{port}/healthy", timeout=5.0)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_birdnet_healthy(self, birdnet_container: DockerContainer) -> None:
        """BirdNET /healthy returns 200 with status ok."""
        host = birdnet_container.get_container_host_ip()
        port = int(birdnet_container.get_exposed_port(9500))
        resp = httpx.get(f"http://{host}:{port}/healthy", timeout=5.0)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_web_mock_healthy(self, web_mock_container: DockerContainer) -> None:
        """Web-Mock /healthy returns 200 with status ok."""
        host = web_mock_container.get_container_host_ip()
        port = int(web_mock_container.get_exposed_port(8001))
        resp = httpx.get(f"http://{host}:{port}/healthy", timeout=5.0)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_db_viewer_healthy(self, db_viewer_container: DockerContainer) -> None:
        """DB-Viewer root (index) returns 200 HTML response."""
        host = db_viewer_container.get_container_host_ip()
        port = int(db_viewer_container.get_exposed_port(8002))
        resp = httpx.get(f"http://{host}:{port}/", timeout=5.0)
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "").lower()


def _poll_redis_key(redis_client: Redis, key: str, timeout: float = 30.0) -> dict[str, Any]:
    """Poll Redis for a key until it exists or timeout. Returns parsed JSON."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = redis_client.get(key)
        if raw is not None:
            return json.loads(str(raw))  # type: ignore[no-any-return]
        time.sleep(2)
    msg = f"Redis key '{key}' not found within {timeout}s"
    raise TimeoutError(msg)


@pytest.mark.smoke
class TestServiceHeartbeats:
    """Verify services publish heartbeats to Redis (container-to-container)."""

    def test_controller_heartbeat_in_redis(
        self,
        controller_container: DockerContainer,
        redis_container_smoke: DockerContainer,
    ) -> None:
        """Controller writes a heartbeat to Redis with host_resources."""
        # Connect to Redis from the test host (via exposed port)
        host = redis_container_smoke.get_container_host_ip()
        port = int(redis_container_smoke.get_exposed_port(6379))
        redis_client = Redis(host=host, port=port, decode_responses=True)

        payload = _poll_redis_key(redis_client, "silvasonic:status:controller")

        assert payload["service"] == "controller"
        assert payload["instance_id"] == "controller"
        assert payload["health"]["status"] == "ok"
        assert "resources" in payload["meta"]
        assert "host_resources" in payload["meta"], (
            "Controller heartbeat should include host_resources"
        )

        redis_client.close()

    def test_recorder_heartbeat_in_redis(
        self,
        recorder_container: DockerContainer,
        redis_container_smoke: DockerContainer,
    ) -> None:
        """Recorder writes a heartbeat to Redis."""
        host = redis_container_smoke.get_container_host_ip()
        port = int(redis_container_smoke.get_exposed_port(6379))
        redis_client = Redis(host=host, port=port, decode_responses=True)

        payload = _poll_redis_key(redis_client, "silvasonic:status:recorder")

        assert payload["service"] == "recorder"
        assert payload["instance_id"] == "recorder"
        assert payload["health"]["status"] == "ok"
        assert "resources" in payload["meta"]
        # Phase 4: dual-stream flags must be present in heartbeat
        assert "recording" in payload["meta"]
        assert "raw_enabled" in payload["meta"]["recording"]
        assert "processed_enabled" in payload["meta"]["recording"]

        # Phase 5: watchdog fields must be present in heartbeat
        assert "watchdog_restarts" in payload["meta"]["recording"]
        assert "watchdog_max_restarts" in payload["meta"]["recording"]
        assert "watchdog_giving_up" in payload["meta"]["recording"]
        assert "watchdog_last_failure" in payload["meta"]["recording"]

        redis_client.close()

    def test_processor_heartbeat_in_redis(
        self,
        processor_container: DockerContainer,
        redis_container_smoke: DockerContainer,
    ) -> None:
        """Processor writes a heartbeat to Redis."""
        host = redis_container_smoke.get_container_host_ip()
        port = int(redis_container_smoke.get_exposed_port(6379))
        redis_client = Redis(host=host, port=port, decode_responses=True)

        payload = _poll_redis_key(redis_client, "silvasonic:status:processor")

        assert payload["service"] == "processor"
        assert payload["instance_id"] == "processor"
        assert payload["health"]["status"] == "ok"
        assert "resources" in payload["meta"]

        redis_client.close()

    def test_birdnet_heartbeat_in_redis(
        self,
        birdnet_container: DockerContainer,
        redis_container_smoke: DockerContainer,
    ) -> None:
        """BirdNET writes a heartbeat to Redis with backlog metrics."""
        host = redis_container_smoke.get_container_host_ip()
        port = int(redis_container_smoke.get_exposed_port(6379))
        redis_client = Redis(host=host, port=port, decode_responses=True)

        payload = _poll_redis_key(redis_client, "silvasonic:status:birdnet")

        assert payload["service"] == "birdnet"
        assert payload["instance_id"] == "birdnet"
        assert payload["health"]["status"] == "ok"
        assert "resources" in payload["meta"]
        assert "analysis" in payload["meta"]
        assert "backlog_pending" in payload["meta"]["analysis"]
        assert "total_analyzed" in payload["meta"]["analysis"]
        assert "total_detections" in payload["meta"]["analysis"]
        assert "total_errors" in payload["meta"]["analysis"]
        assert "avg_inference_ms" in payload["meta"]["analysis"]

        redis_client.close()


def _extract_pg_errors(logs: str) -> list[str]:
    """Extract PostgreSQL ERROR and FATAL log lines with their DETAIL/HINT context.

    PostgreSQL logs multi-line error blocks like::

        ERROR:  insert or update on table "recordings" violates foreign key ...
        DETAIL:  Key (sensor_id)=(ghost) is not present in table "devices".
        STATEMENT:  INSERT INTO recordings ...

    This function collects the ERROR/FATAL line plus any immediately following
    DETAIL, HINT, CONTEXT, or STATEMENT lines as a single block.

    Returns:
        A list of error blocks, each as a joined multi-line string.
    """
    lines = logs.splitlines()
    errors: list[str] = []
    i = 0
    # Context prefixes that PostgreSQL appends after an ERROR line
    continuation_markers = ("DETAIL:", "HINT:", "CONTEXT:", "STATEMENT:")

    while i < len(lines):
        line = lines[i]
        # Match PostgreSQL log format: "... ERROR:" or "... FATAL:"
        if " ERROR:" in line or " FATAL:" in line:
            block = [line.strip()]
            # Collect continuation lines (DETAIL, HINT, STATEMENT)
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                # Check if line contains any continuation marker
                if any(marker in next_line for marker in continuation_markers):
                    block.append(next_line)
                    j += 1
                else:
                    break
            errors.append("\n".join(block))
            i = j
        else:
            i += 1

    return errors


def _deduplicate_errors(errors: list[str]) -> list[str]:
    """Remove duplicate error blocks, preserving order."""
    seen: set[str] = set()
    unique: list[str] = []
    for err in errors:
        if err not in seen:
            seen.add(err)
            unique.append(err)
    return unique


@pytest.mark.smoke
class TestDatabaseIntegrity:
    """Verify the database container has no errors during smoke test operation.

    This is a generic safety-net test that catches any PostgreSQL errors
    (FK violations, constraint errors, connection failures, etc.) that
    occurred while other smoke tests were running.  If this test fails,
    the assertion message includes the exact error lines from the DB logs
    for immediate debugging.
    """

    def test_no_database_errors(
        self,
        database_container: DockerContainer,
        controller_container: DockerContainer,
        processor_container: DockerContainer,
    ) -> None:
        """Database container logs must contain zero ERROR or FATAL entries.

        Depends on controller and processor containers to ensure their
        interactions with the database have already occurred before we
        inspect the logs.  This catches issues like:
        - Foreign key constraint violations
        - Schema migration failures
        - Connection pool exhaustion
        - Data type mismatches
        """
        # Ensure fixtures ran — no-op but establishes dependency ordering
        _ = controller_container
        _ = processor_container

        # Give the DB a moment to flush any pending log writes
        time.sleep(1)

        _stdout, stderr = database_container.get_logs()
        db_logs = (stderr or b"").decode(errors="replace")

        # PostgreSQL writes errors to stderr
        errors = _extract_pg_errors(db_logs)

        # Filter out expected, harmless messages
        filtered: list[str] = []
        harmless_patterns = [
            # TimescaleDB startup noise
            "FATAL:  the database system is starting up",
            "FATAL:  the database system is shutting down",
        ]
        for err in errors:
            if not any(pattern in err for pattern in harmless_patterns):
                filtered.append(err)

        filtered = _deduplicate_errors(filtered)

        if filtered:
            # Build a detailed failure message for debugging
            error_report = "\n\n".join(f"  [{i + 1}] {err}" for i, err in enumerate(filtered))
            msg = (
                f"\n{'=' * 72}\n"
                f"  DATABASE ERROR LOG — {len(filtered)} error(s) detected\n"
                f"{'=' * 72}\n\n"
                f"{error_report}\n\n"
                f"{'=' * 72}\n"
                f"  These errors occurred during smoke test operation.\n"
                f"  Common causes:\n"
                f"    • FK violation: device not enrolled before recording indexed\n"
                f"    • Schema mismatch: init SQL out of sync with application code\n"
                f"    • Connection issues: service started before DB was ready\n"
                f"{'=' * 72}"
            )
            pytest.fail(msg)
