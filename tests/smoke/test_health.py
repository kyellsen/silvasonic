"""Smoke tests — health probes and heartbeat verification for all Silvasonic services.

Each test uses testcontainer fixtures (from conftest.py) to spin up
isolated, ephemeral containers with random ports. No conflicts with
the dev stack, no host-filesystem writes, automatic cleanup.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from redis import Redis
from testcontainers.core.container import DockerContainer


@pytest.mark.smoke
class TestServiceHealth:
    """Verify all services respond to health probes via testcontainers."""

    def test_database_created(
        self, controller_container: DockerContainer, database_dir: Path
    ) -> None:
        """The Controller's first connection creates the station database file.

        SQLite has no server to probe: the database is healthy when the file
        exists in the shared directory and carries the schema (ADR-0037).
        """
        _ = controller_container
        db = database_dir / "silvasonic.db"
        assert db.is_file(), f"no database file in {database_dir}"
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
        finally:
            con.close()
        assert version == 1
        assert "recordings" in tables

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

    def test_gateway_rejects_missing_credentials(self, gateway_container: DockerContainer) -> None:
        """Gateway answers 401 without credentials (per-installation login, 23d5e6f)."""
        host = gateway_container.get_container_host_ip()
        port = int(gateway_container.get_exposed_port(80))
        resp = httpx.get(
            f"http://{host}:{port}/web-mock/healthy",
            timeout=5.0,
            headers={"Host": "localhost"},
        )
        assert resp.status_code == 401, (
            f"Gateway should return 401 (basic_auth) but got {resp.status_code}"
        )

    def test_gateway_serves_http(
        self, gateway_container: DockerContainer, gateway_credentials: tuple[str, str]
    ) -> None:
        """Gateway (Caddy) serves HTTP to a client logged in with the test credential."""
        host = gateway_container.get_container_host_ip()
        port = int(gateway_container.get_exposed_port(80))
        resp = httpx.get(
            f"http://{host}:{port}/web-mock/healthy",
            timeout=5.0,
            headers={"Host": "localhost"},
            auth=gateway_credentials,
        )
        assert resp.status_code != 401, "Valid credentials must pass basic_auth"
        assert resp.status_code < 500

    def test_gateway_proxies_to_web_mock(
        self, gateway_container: DockerContainer, gateway_credentials: tuple[str, str]
    ) -> None:
        """Gateway proxies authenticated requests through to web-mock."""
        host = gateway_container.get_container_host_ip()
        port = int(gateway_container.get_exposed_port(80))
        resp = httpx.get(
            f"http://{host}:{port}/web-mock/healthy",
            timeout=5.0,
            headers={"Host": "localhost"},
            auth=gateway_credentials,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def _poll_redis_key(redis_client: Redis, key: str, timeout: float = 30.0) -> dict[str, Any]:
    """Poll Redis for a key until it exists or timeout. Returns parsed JSON."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = redis_client.get(key)
        if raw is not None:
            return json.loads(str(raw))
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


# Errors a database client logs when SQLite refuses or delays its work
_DB_ERROR_MARKERS = (
    "IntegrityError",
    "OperationalError",
    "database is locked",
    "database.slow_transaction",
    "SchemaVersionError",
)


@pytest.mark.smoke
class TestDatabaseIntegrity:
    """Verify the station database stayed consistent during smoke test operation.

    SQLite has no server log: errors surface in the clients.  This safety net
    checks the file itself (integrity, foreign keys) and scans the logs of
    the services that wrote to it while the other smoke tests ran.
    """

    def test_no_database_errors(
        self,
        database_dir: Path,
        controller_container: DockerContainer,
        processor_container: DockerContainer,
    ) -> None:
        """The file passes SQLite's checks and no client logged a database error.

        Catches, among others:
        - Foreign key violations (device not enrolled before recording indexed)
        - Schema mismatches between schema.sql and the ORM models
        - Writers waiting past the busy timeout ("database is locked")
        """
        db = database_dir / "silvasonic.db"
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            integrity = con.execute("PRAGMA integrity_check").fetchall()
            fk_violations = con.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            con.close()
        assert integrity == [("ok",)], f"integrity_check: {integrity}"
        assert fk_violations == [], f"foreign_key_check: {fk_violations}"

        problems: list[str] = []
        for name, container in (
            ("controller", controller_container),
            ("processor", processor_container),
        ):
            stdout, stderr = container.get_logs()
            logs = (stdout or b"").decode(errors="replace") + (stderr or b"").decode(
                errors="replace"
            )
            problems += [
                f"{name}: {line.strip()}"
                for line in logs.splitlines()
                if any(marker in line for marker in _DB_ERROR_MARKERS)
            ]
        assert not problems, "database errors in service logs:\n" + "\n".join(
            dict.fromkeys(problems)
        )
