"""Unit tests for silvasonic-core package — comprehensive coverage.

Tests all core modules: HealthMonitor, ResourceCollector, HostResourceCollector,
HeartbeatPublisher, HeartbeatPayload, SilvaService, get_redis_connection,
and ConfigSchemas.
"""

import asyncio
import signal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.config_schemas import (
    BirdnetSettings,
    ProcessorSettings,
    SystemSettings,
    UploaderSettings,
)
from silvasonic.core.health import HealthMonitor
from silvasonic.core.heartbeat import HeartbeatPayload, HeartbeatPublisher
from silvasonic.core.resources import HostResourceCollector, ResourceCollector

# ---------------------------------------------------------------------------
# §1 — Package-Level Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPackage:
    """Basic package-level tests."""

    def test_version_exists(self) -> None:
        """Core package exposes a version string."""
        from silvasonic.core import __version__

        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_configure_logging_callable(self) -> None:
        """configure_logging is importable and callable."""
        from silvasonic.core.logging import configure_logging

        assert callable(configure_logging)

    def test_health_server_callable(self) -> None:
        """start_health_server is importable and callable."""
        from silvasonic.core.health import start_health_server

        assert callable(start_health_server)
        # Verify the updated signature (port + monitor) is accepted without error
        import inspect

        sig = inspect.signature(start_health_server)
        assert "monitor" in sig.parameters


# ---------------------------------------------------------------------------
# §2 — HealthMonitor Tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# §3 — ResourceCollector Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResourceCollector:
    """Tests for per-process resource collection."""

    @patch("silvasonic.core.resources.psutil.Process")
    def test_collect_basic_metrics(self, mock_process_cls: MagicMock) -> None:
        """Collects CPU, memory, and thread count."""
        proc = MagicMock()
        proc.cpu_percent.return_value = 12.3
        proc.memory_info.return_value = MagicMock(rss=100 * 1024 * 1024)  # 100 MB
        proc.num_threads.return_value = 4
        mock_process_cls.return_value = proc

        rc = ResourceCollector()
        result = rc.collect()

        assert result["cpu_percent"] == 12.3
        assert result["memory_mb"] == 100.0
        assert result["num_threads"] == 4

    @patch("silvasonic.core.resources.shutil.disk_usage")
    @patch("silvasonic.core.resources.psutil.Process")
    def test_collect_with_storage(
        self, mock_process_cls: MagicMock, mock_disk: MagicMock, tmp_path: Path
    ) -> None:
        """Includes storage metrics when workspace_path is set."""
        proc = MagicMock()
        proc.cpu_percent.return_value = 5.0
        proc.memory_info.return_value = MagicMock(rss=50 * 1024 * 1024)
        proc.num_threads.return_value = 2
        mock_process_cls.return_value = proc

        mock_disk.return_value = MagicMock(
            used=100 * 1024**3,
            total=500 * 1024**3,  # 100 GB  # 500 GB
        )

        rc = ResourceCollector(workspace_path=tmp_path)
        result = rc.collect()

        assert "storage_used_gb" in result
        assert "storage_total_gb" in result
        assert "storage_percent" in result
        assert result["storage_percent"] == 20.0

    @patch("silvasonic.core.resources.psutil.Process")
    def test_collect_handles_exception(self, mock_process_cls: MagicMock) -> None:
        """Returns empty dict on psutil errors."""
        proc = MagicMock()
        # First call (init priming) succeeds, second call (collect) raises
        proc.cpu_percent.side_effect = [0.0, RuntimeError("no process")]
        mock_process_cls.return_value = proc

        rc = ResourceCollector()
        result = rc.collect()

        assert result == {}


# ---------------------------------------------------------------------------
# §4 — HostResourceCollector Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHostResourceCollector:
    """Tests for host-level resource collection (Controller)."""

    @patch("silvasonic.core.resources.psutil.cpu_count", return_value=4)
    @patch("silvasonic.core.resources.psutil.cpu_percent", return_value=23.5)
    @patch("silvasonic.core.resources.psutil.virtual_memory")
    def test_collect_host_metrics(
        self,
        mock_vmem: MagicMock,
        mock_cpu_pct: MagicMock,
        mock_cpu_cnt: MagicMock,
    ) -> None:
        """Collects host CPU, memory, and count."""
        mock_vmem.return_value = MagicMock(
            used=2048 * 1024 * 1024,
            total=8192 * 1024 * 1024,
            percent=25.0,
        )

        hrc = HostResourceCollector()
        result = hrc.collect()

        assert result["cpu_percent"] == 23.5
        assert result["cpu_count"] == 4
        assert result["memory_percent"] == 25.0

    @patch("silvasonic.core.resources.psutil.cpu_percent", side_effect=RuntimeError)
    def test_collect_handles_exception(self, mock_cpu: MagicMock) -> None:
        """Returns empty dict on errors."""
        hrc = HostResourceCollector()
        result = hrc.collect()

        assert result == {}


# ---------------------------------------------------------------------------
# §5 — HeartbeatPayload Pydantic Model Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHeartbeatPayload:
    """Tests for the Pydantic heartbeat payload model."""

    def test_valid_payload(self) -> None:
        """A valid payload instantiates and serializes correctly."""
        p = HeartbeatPayload(
            service="recorder",
            instance_id="ultramic-01",
            timestamp=1706612400.123,
            health={"status": "ok", "components": {}},
            activity="recording",
            meta={"resources": {"cpu_percent": 12.3}},
        )

        d = p.model_dump()
        assert d["service"] == "recorder"
        assert d["instance_id"] == "ultramic-01"
        assert d["activity"] == "recording"

    def test_missing_field_raises(self) -> None:
        """Missing required fields raise ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HeartbeatPayload(service="test")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# §6 — HeartbeatPublisher Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHeartbeatPublisher:
    """Tests for the HeartbeatPublisher."""

    def _make_publisher(self) -> tuple[HeartbeatPublisher, AsyncMock]:
        """Create a publisher with a mocked Redis client."""
        redis_mock = AsyncMock()
        pub = HeartbeatPublisher(
            redis=redis_mock,
            service_name="test-service",
            instance_id="test-01",
            interval=1.0,
        )
        return pub, redis_mock

    def test_build_payload_returns_pydantic_model(self) -> None:
        """_build_payload returns a HeartbeatPayload instance."""
        pub, _ = self._make_publisher()
        payload = pub._build_payload({"cpu_percent": 5.0})

        assert isinstance(payload, HeartbeatPayload)
        assert payload.service == "test-service"
        assert payload.instance_id == "test-01"
        assert payload.meta["resources"]["cpu_percent"] == 5.0

    def test_build_payload_with_health_provider(self) -> None:
        """Health provider function is called and integrated."""
        pub, _ = self._make_publisher()
        pub.set_health_provider(lambda: {"status": "ok", "components": {"main": {"healthy": True}}})
        payload = pub._build_payload({})

        assert payload.health["status"] == "ok"
        assert "main" in payload.health["components"]

    def test_build_payload_health_provider_error(self) -> None:
        """Gracefully handles health provider exceptions."""
        pub, _ = self._make_publisher()

        def broken_health() -> dict[str, Any]:
            raise RuntimeError("broken")

        pub.set_health_provider(broken_health)
        payload = pub._build_payload({})

        assert payload.health["status"] == "error"

    def test_build_payload_with_meta_provider(self) -> None:
        """Meta provider fields are merged into meta."""
        pub, _ = self._make_publisher()
        pub.set_meta_provider(lambda: {"db_level": -45.2})
        payload = pub._build_payload({"cpu_percent": 1.0})

        assert payload.meta["db_level"] == -45.2
        assert payload.meta["resources"]["cpu_percent"] == 1.0

    def test_set_activity(self) -> None:
        """Activity label is included in payload."""
        pub, _ = self._make_publisher()
        pub.set_activity("recording")
        payload = pub._build_payload({})

        assert payload.activity == "recording"

    @pytest.mark.asyncio
    async def test_publish_once_calls_set_and_publish(self) -> None:
        """publish_once performs both SET (with TTL) and PUBLISH."""
        pub, redis_mock = self._make_publisher()
        await pub.publish_once({"cpu_percent": 3.0})

        redis_mock.set.assert_called_once()
        call_args = redis_mock.set.call_args
        assert call_args[0][0] == "silvasonic:status:test-01"
        assert call_args[1]["ex"] == 30

        redis_mock.publish.assert_called_once()
        pub_args = redis_mock.publish.call_args
        assert pub_args[0][0] == "silvasonic:status"

    @pytest.mark.asyncio
    async def test_publish_once_handles_redis_error(self) -> None:
        """publish_once catches Redis errors without raising."""
        pub, redis_mock = self._make_publisher()
        redis_mock.set.side_effect = ConnectionError("Redis down")

        # Should NOT raise
        await pub.publish_once({})

    @pytest.mark.asyncio
    async def test_start_and_stop(self) -> None:
        """Start creates a background task, stop cancels it."""
        pub, _ = self._make_publisher()
        collector = MagicMock()
        collector.collect.return_value = {}

        task = pub.start(collector)
        assert isinstance(task, asyncio.Task)
        assert not task.done()

        await pub.stop()
        assert task.done()


# ---------------------------------------------------------------------------
# §7 — get_redis_connection Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetRedisConnection:
    """Tests for the shared Redis connection helper."""

    @pytest.mark.asyncio
    @patch("silvasonic.core.redis.Redis")
    async def test_successful_connection(self, mock_redis_cls: MagicMock) -> None:
        """Returns a Redis client on success."""
        from silvasonic.core.redis import get_redis_connection

        mock_client = AsyncMock()
        mock_redis_cls.from_url.return_value = mock_client

        result = await get_redis_connection("redis://localhost:6379/0")

        assert result is mock_client
        mock_client.ping.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("silvasonic.core.redis.Redis")
    async def test_connection_failure_returns_none(self, mock_redis_cls: MagicMock) -> None:
        """Returns None if Redis is unreachable."""
        from silvasonic.core.redis import get_redis_connection

        mock_client = AsyncMock()
        mock_client.ping.side_effect = ConnectionError("unreachable")
        mock_redis_cls.from_url.return_value = mock_client

        result = await get_redis_connection("redis://localhost:6379/0")

        assert result is None


# ---------------------------------------------------------------------------
# §8 — SilvaService Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSilvaService:
    """Tests for the SilvaService base class."""

    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    async def test_setup_without_redis(
        self,
        mock_rc: MagicMock,
        mock_logging: MagicMock,
        mock_health_server: MagicMock,
    ) -> None:
        """Setup completes even when Redis is unavailable."""
        from unittest.mock import ANY

        from silvasonic.core.service import SilvaService

        class TestService(SilvaService):
            """Test service."""

            service_name = "test"
            service_port = 19999

            async def run(self) -> None:
                """No-op."""

        with patch(
            "silvasonic.core.service_context.get_redis_connection",
            new_callable=AsyncMock,
        ) as mock_redis:
            mock_redis.return_value = None

            svc = TestService()
            await svc._setup()

            mock_logging.assert_called_once_with("test")
            mock_health_server.assert_called_once_with(port=19999, monitor=ANY)
            assert svc._ctx.heartbeat is None

    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    async def test_setup_with_redis(
        self,
        mock_rc: MagicMock,
        mock_logging: MagicMock,
        mock_health_server: MagicMock,
    ) -> None:
        """Setup starts heartbeat when Redis is available."""
        from silvasonic.core.service import SilvaService

        class TestService(SilvaService):
            """Test service."""

            service_name = "test"
            service_port = 19999

            async def run(self) -> None:
                """No-op."""

        redis_mock = AsyncMock()
        with patch(
            "silvasonic.core.service_context.get_redis_connection", new_callable=AsyncMock
        ) as mock_conn:
            mock_conn.return_value = redis_mock

            svc = TestService()
            await svc._setup()

            assert svc._ctx.heartbeat is not None
            # Cleanup
            await svc._teardown()

    def test_run_not_implemented(self) -> None:
        """SilvaService.run() raises NotImplementedError."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        with pytest.raises(NotImplementedError):
            asyncio.get_event_loop().run_until_complete(svc.run())

    def test_handle_signal_sets_event(self) -> None:
        """Signal handler sets the shutdown event."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        assert not svc._shutdown_event.is_set()

        svc._handle_signal(signal.SIGTERM)
        assert svc._shutdown_event.is_set()


# ---------------------------------------------------------------------------
# §9 — Config Schemas Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConfigSchemas:
    """Tests for Pydantic configuration schemas."""

    def test_system_settings_defaults(self) -> None:
        """SystemSettings has correct defaults."""
        s = SystemSettings()
        assert s.latitude == 53.55
        assert s.longitude == 9.99
        assert s.max_recorders == 5
        assert s.station_name == "Silvasonic Dev"

    def test_birdnet_settings_defaults(self) -> None:
        """BirdnetSettings has correct defaults."""
        s = BirdnetSettings()
        assert s.confidence_threshold == 0.25

    def test_processor_settings_defaults(self) -> None:
        """ProcessorSettings has correct defaults."""
        s = ProcessorSettings()
        assert s.janitor_threshold_warning == 70.0
        assert s.janitor_threshold_critical == 80.0
        assert s.janitor_threshold_emergency == 90.0
        assert s.indexer_poll_interval == 5.0

    def test_uploader_settings_defaults(self) -> None:
        """UploaderSettings has correct defaults."""
        s = UploaderSettings()
        assert s.enabled is True
        assert s.bandwidth_limit == "1M"
        assert s.schedule_start_hour == 22
        assert s.schedule_end_hour == 6

    def test_system_settings_override(self) -> None:
        """SystemSettings accepts overrides."""
        s = SystemSettings(latitude=48.13, longitude=11.58, station_name="München")
        assert s.latitude == 48.13
        assert s.station_name == "München"


# ---------------------------------------------------------------------------
# §10 — HealthMonitor Liveness Watchdog Tests (Fix #4)
# ---------------------------------------------------------------------------


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
        import time as _time

        hm = HealthMonitor(liveness_timeout=60.0)
        # Simulate last touch far in the past by directly setting _last_touch
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
        """Overall status is 'error' if service is frozen (watchdog triggered)."""
        import time as _time

        hm = HealthMonitor(liveness_timeout=60.0)
        with hm._lock:
            hm._last_touch = _time.monotonic() - 61.0
            hm._liveness_enabled = True
        status = hm.get_status()
        assert status["status"] == "error"
        assert status["live"] is False


# ---------------------------------------------------------------------------
# §11 — SilvaService Hardening Tests (Fixes #1, #2, #3)
# ---------------------------------------------------------------------------


def _make_test_service() -> "Any":
    """Helper: build a minimal concrete SilvaService subclass."""
    from silvasonic.core.service import SilvaService

    class _Svc(SilvaService):
        service_name = "test"
        service_port = 19998

        async def run(self) -> None:
            """No-op placeholder."""

    return _Svc


@pytest.mark.unit
class TestSilvaServiceHardening:
    """Tests for active signal cancel, dying-gasp, and load_config hook."""

    def test_handle_signal_cancels_run_task(self) -> None:
        """Signal handler cancels _run_task when it exists (Fix #2)."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        svc._run_task = mock_task

        svc._handle_signal(signal.SIGTERM)

        assert svc._shutdown_event.is_set()
        mock_task.cancel.assert_called_once()

    def test_handle_signal_no_task_does_not_raise(self) -> None:
        """Signal handler works safely when _run_task is None (Fix #2)."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        svc._run_task = None
        # Must not raise
        svc._handle_signal(signal.SIGTERM)
        assert svc._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_dying_gasp_published_on_run_exception(self) -> None:
        """On unexpected crash in run(), dying-gasp heartbeat is published (Fix #3)."""
        from silvasonic.core.service import SilvaService

        class _CrashSvc(SilvaService):
            service_name = "crasher"
            service_port = 19997

            async def run(self) -> None:
                raise RuntimeError("boom")

        svc = _CrashSvc()
        mock_heartbeat = AsyncMock()
        mock_rc = MagicMock()
        mock_rc.collect.return_value = {}
        svc._ctx.heartbeat = mock_heartbeat
        svc._ctx.resource_collector = mock_rc

        await svc._publish_dying_gasp(RuntimeError("boom"))

        mock_heartbeat.publish_once.assert_awaited_once()
        status = svc.health.get_status()
        assert status["status"] == "error"

    @pytest.mark.asyncio
    async def test_dying_gasp_without_heartbeat_does_not_raise(self) -> None:
        """_publish_dying_gasp is safe when Redis is unavailable (Fix #3)."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        svc._ctx.heartbeat = None
        svc._ctx.resource_collector = None
        # Must not raise
        await svc._publish_dying_gasp(RuntimeError("no redis"))

    @pytest.mark.asyncio
    async def test_load_config_default_is_noop(self) -> None:
        """Default load_config() completes without error (Fix #1)."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        # Must not raise
        await svc.load_config()

    @pytest.mark.asyncio
    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    async def test_load_config_called_during_setup(
        self,
        mock_rc: MagicMock,
        mock_log: MagicMock,
        mock_hs: MagicMock,
    ) -> None:
        """load_config() is awaited inside _setup() (Fix #1)."""
        from silvasonic.core.service import SilvaService

        config_called = []

        class _ConfigSvc(SilvaService):
            service_name = "cfgsvc"
            service_port = 19996

            async def load_config(self) -> None:
                config_called.append(True)

            async def run(self) -> None:
                """No-op."""

        with patch(
            "silvasonic.core.service_context.get_redis_connection", new_callable=AsyncMock
        ) as mock_conn:
            mock_conn.return_value = None
            svc = _ConfigSvc()
            await svc._setup()

        assert config_called == [True], "load_config() was not called during _setup()"

    @pytest.mark.asyncio
    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    async def test_load_config_exception_does_not_abort_setup(
        self,
        mock_rc: MagicMock,
        mock_log: MagicMock,
        mock_hs: MagicMock,
    ) -> None:
        """A failing load_config() only logs a warning — setup continues (Fix #1)."""
        from silvasonic.core.service import SilvaService

        class _BrokenConfigSvc(SilvaService):
            service_name = "broken"
            service_port = 19995

            async def load_config(self) -> None:
                raise ConnectionError("db unreachable")

            async def run(self) -> None:
                """No-op."""

        with patch(
            "silvasonic.core.service_context.get_redis_connection", new_callable=AsyncMock
        ) as mock_conn:
            mock_conn.return_value = None
            svc = _BrokenConfigSvc()
            # Must not raise — just logs a warning
            await svc._setup()


# ---------------------------------------------------------------------------
# §12 — Health HTTP Handler Tests (_make_handler)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHealthHandler:
    """Tests for the _make_handler HTTP request handler factory."""

    def _make_mock_request(self, monitor: HealthMonitor, path: str = "/healthy") -> Any:
        """Create a mock HTTP request dispatched through _make_handler."""
        from io import BytesIO

        from silvasonic.core.health import _make_handler

        handler_cls = _make_handler(monitor)

        # Create handler instance without actually binding to a socket.
        # We use Any-typed reference so mypy doesn't complain about setting
        # internal attributes on BaseHTTPRequestHandler.
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


# ---------------------------------------------------------------------------
# §13 — _collect_disk_usage Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCollectDiskUsage:
    """Tests for _collect_disk_usage helper function."""

    def test_nonexistent_path_returns_none(self) -> None:
        """Returns None for paths that don't exist."""
        from silvasonic.core.resources import _collect_disk_usage

        result = _collect_disk_usage(Path("/nonexistent/path/should/not/exist"))
        assert result is None


# ---------------------------------------------------------------------------
# §14 — HostResourceCollector with Storage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHostResourceCollectorWithStorage:
    """Tests for HostResourceCollector with storage path."""

    @patch("silvasonic.core.resources._collect_disk_usage")
    @patch("silvasonic.core.resources.psutil.cpu_count", return_value=8)
    @patch("silvasonic.core.resources.psutil.cpu_percent", return_value=15.0)
    @patch("silvasonic.core.resources.psutil.virtual_memory")
    def test_collect_includes_storage(
        self,
        mock_vmem: MagicMock,
        mock_cpu_pct: MagicMock,
        mock_cpu_cnt: MagicMock,
        mock_disk: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Includes storage metrics when storage_path is set."""
        mock_vmem.return_value = MagicMock(
            used=4096 * 1024 * 1024,
            total=16384 * 1024 * 1024,
            percent=25.0,
        )
        mock_disk.return_value = (200.0, 1000.0, 20.0)

        hrc = HostResourceCollector(storage_path=tmp_path)
        result = hrc.collect()

        assert result["storage_used_gb"] == 200.0
        assert result["storage_total_gb"] == 1000.0
        assert result["storage_percent"] == 20.0


# ---------------------------------------------------------------------------
# §15 — HeartbeatPublisher Additional Coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHeartbeatPublisherAdditional:
    """Additional tests for HeartbeatPublisher edge cases."""

    def _make_publisher(self) -> tuple[HeartbeatPublisher, AsyncMock]:
        """Create a publisher with a mocked Redis client."""
        redis_mock = AsyncMock()
        pub = HeartbeatPublisher(
            redis=redis_mock,
            service_name="test-service",
            instance_id="test-01",
            interval=0.01,  # short interval for loop test
        )
        return pub, redis_mock

    def test_meta_provider_exception_handled(self) -> None:
        """Meta provider exception results in meta without extra fields."""
        pub, _ = self._make_publisher()

        def broken_meta() -> dict[str, Any]:
            raise RuntimeError("broken meta")

        pub.set_meta_provider(broken_meta)
        payload = pub._build_payload({"cpu_percent": 1.0})

        # Meta should still have resources, but no extra fields from broken provider
        assert "resources" in payload.meta
        assert payload.meta["resources"]["cpu_percent"] == 1.0

    def test_meta_provider_non_dict_ignored(self) -> None:
        """Meta provider returning non-dict is not merged."""
        pub, _ = self._make_publisher()

        def bad_meta() -> Any:
            return "not a dict"

        pub.set_meta_provider(bad_meta)
        payload = pub._build_payload({})

        # Should not crash; meta should still have resources
        assert "resources" in payload.meta

    @pytest.mark.asyncio
    async def test_loop_collects_and_publishes(self) -> None:
        """The _loop coroutine calls collect() and publish_once()."""
        pub, redis_mock = self._make_publisher()
        collector = MagicMock()
        collector.collect.return_value = {"cpu_percent": 5.0}

        pub.start(collector)
        # Let loop run at least one iteration
        import asyncio

        await asyncio.sleep(0.05)
        await pub.stop()

        collector.collect.assert_called()
        redis_mock.set.assert_called()

    @pytest.mark.asyncio
    async def test_loop_handles_exception(self) -> None:
        """_loop continues after a non-cancellation exception."""
        pub, _ = self._make_publisher()
        collector = MagicMock()
        # First collect raises, second succeeds
        collector.collect.side_effect = [RuntimeError("oops"), {"cpu": 1.0}]

        pub.start(collector)
        import asyncio

        await asyncio.sleep(0.05)
        await pub.stop()

        assert collector.collect.call_count >= 1


# ---------------------------------------------------------------------------
# §16 — SilvaService get_extra_meta & _main Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSilvaServiceLifecycle:
    """Tests for SilvaService._main lifecycle and get_extra_meta."""

    def test_get_extra_meta_returns_empty_dict(self) -> None:
        """Default get_extra_meta returns an empty dict."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        assert svc.get_extra_meta() == {}

    @pytest.mark.asyncio
    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    @patch("silvasonic.core.service_context.get_redis_connection", new_callable=AsyncMock)
    async def test_main_lifecycle_normal_shutdown(
        self,
        mock_redis: AsyncMock,
        mock_rc: MagicMock,
        mock_log: MagicMock,
        mock_hs: MagicMock,
    ) -> None:
        """_main: setup → run → teardown completes for graceful shutdown."""
        from silvasonic.core.service import SilvaService

        mock_redis.return_value = None

        class _QuickSvc(SilvaService):
            service_name = "quick"
            service_port = 19990

            async def run(self) -> None:
                # Signal immediate shutdown
                self._shutdown_event.set()

        svc = _QuickSvc()
        # Can't use start() (it calls asyncio.run()), so call _main() directly
        await svc._main()

    @pytest.mark.asyncio
    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    @patch("silvasonic.core.service_context.get_redis_connection", new_callable=AsyncMock)
    async def test_main_lifecycle_crash_publishes_dying_gasp(
        self,
        mock_redis: AsyncMock,
        mock_rc: MagicMock,
        mock_log: MagicMock,
        mock_hs: MagicMock,
    ) -> None:
        """_main: crashes in run() trigger dying gasp and re-raise."""
        from silvasonic.core.service import SilvaService

        mock_redis.return_value = None

        class _CrashSvc(SilvaService):
            service_name = "crasher"
            service_port = 19989

            async def run(self) -> None:
                raise RuntimeError("fatal error")

        svc = _CrashSvc()
        with pytest.raises(RuntimeError, match="fatal error"):
            await svc._main()

    def test_health_property_delegates_to_ctx(self) -> None:
        """The health property returns the HealthMonitor from ServiceContext."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        assert svc.health is svc._ctx.health

    @pytest.mark.asyncio
    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    @patch("silvasonic.core.service_context.get_redis_connection", new_callable=AsyncMock)
    async def test_main_cancelled_error_on_signal(
        self,
        mock_redis: AsyncMock,
        mock_rc: MagicMock,
        mock_log: MagicMock,
        mock_hs: MagicMock,
    ) -> None:
        """_main: signal during run() triggers CancelledError path (line 209)."""
        from silvasonic.core.service import SilvaService

        mock_redis.return_value = None

        class _BlockingSvc(SilvaService):
            service_name = "blocker"
            service_port = 19988

            async def run(self) -> None:
                # Block forever — will be cancelled by _handle_signal
                await asyncio.sleep(3600)

        svc = _BlockingSvc()

        async def cancel_after_start() -> None:
            # Wait until _run_task is set, then simulate signal
            while svc._run_task is None:
                await asyncio.sleep(0.01)
            svc._handle_signal(signal.SIGTERM)

        # Schedule the signal simulation concurrently with _main
        _signal_task = asyncio.create_task(cancel_after_start())

        # _main should complete without raising (CancelledError is caught)
        await svc._main()
        assert svc._shutdown_event.is_set()
        assert _signal_task.done()


# ---------------------------------------------------------------------------
# §14 — start_health_server Real-Socket Test
# ---------------------------------------------------------------------------


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
            # Discover the OS-assigned port
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


# ---------------------------------------------------------------------------
# §16 — Lazy Database Session Initialization (R-01)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLazySessionInit:
    """Verify that importing session.py does NOT create an engine eagerly."""

    def test_import_does_not_create_engine(self) -> None:
        """Importing session module should not trigger engine creation."""
        import importlib

        from silvasonic.core.database import session

        session._get_engine.cache_clear()
        session._get_session_factory.cache_clear()
        importlib.reload(session)
        # Cache info shows no calls yet — engine is NOT created at import
        assert session._get_engine.cache_info().currsize == 0
        assert session._get_session_factory.cache_info().currsize == 0

    def test_lazy_factories_are_cached(self) -> None:
        """After first call, subsequent calls return the same cached instance."""
        from unittest.mock import patch as _patch

        from silvasonic.core.database import session

        session._get_engine.cache_clear()
        session._get_session_factory.cache_clear()

        with _patch("silvasonic.core.database.session.create_async_engine") as mock_engine:
            mock_engine.return_value = "fake_engine"
            engine1 = session._get_engine()
            engine2 = session._get_engine()

        assert engine1 is engine2
        # create_async_engine was called only once despite two _get_engine() calls
        mock_engine.assert_called_once()

        # Cleanup
        session._get_engine.cache_clear()
        session._get_session_factory.cache_clear()
