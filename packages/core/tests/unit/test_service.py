"""Unit tests for SilvaService, ConfigSchemas, and lazy DB sessions.

Covers the SilvaService base class lifecycle (_setup, _main, _teardown),
signal handling, dying-gasp, load_config hook, get_extra_meta, health
property, config schemas (System/Birdnet/Processor/Uploader), and lazy
session initialization.
"""

import asyncio
import signal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.config_schemas import (
    BirdnetSettings,
    ProcessorSettings,
    SystemSettings,
    UploaderSettings,
)

# ===================================================================
# Package-level checks
# ===================================================================


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
        import inspect

        from silvasonic.core.health import start_health_server

        assert callable(start_health_server)
        sig = inspect.signature(start_health_server)
        assert "monitor" in sig.parameters


# ===================================================================
# SilvaService
# ===================================================================


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
            "silvasonic.core.service_context.get_redis_connection",
            new_callable=AsyncMock,
        ) as mock_conn:
            mock_conn.return_value = redis_mock

            svc = TestService()
            await svc._setup()

            assert svc._ctx.heartbeat is not None
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

    def test_handle_signal_cancels_run_task(self) -> None:
        """Signal handler cancels _run_task when it exists."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        svc._run_task = mock_task

        svc._handle_signal(signal.SIGTERM)

        assert svc._shutdown_event.is_set()
        mock_task.cancel.assert_called_once()

    def test_handle_signal_no_task_does_not_raise(self) -> None:
        """Signal handler works safely when _run_task is None."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        svc._run_task = None
        svc._handle_signal(signal.SIGTERM)
        assert svc._shutdown_event.is_set()

    async def test_dying_gasp_published_on_run_exception(self) -> None:
        """On unexpected crash, dying-gasp heartbeat is published."""
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

    async def test_dying_gasp_without_heartbeat_does_not_raise(self) -> None:
        """_publish_dying_gasp is safe when Redis is unavailable."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        svc._ctx.heartbeat = None
        svc._ctx.resource_collector = None
        await svc._publish_dying_gasp(RuntimeError("no redis"))

    async def test_load_config_default_is_noop(self) -> None:
        """Default load_config() completes without error."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        await svc.load_config()

    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    async def test_load_config_called_during_setup(
        self,
        mock_rc: MagicMock,
        mock_log: MagicMock,
        mock_hs: MagicMock,
    ) -> None:
        """load_config() is awaited inside _setup()."""
        from silvasonic.core.service import SilvaService

        config_called: list[bool] = []

        class _ConfigSvc(SilvaService):
            service_name = "cfgsvc"
            service_port = 19996

            async def load_config(self) -> None:
                config_called.append(True)

            async def run(self) -> None:
                """No-op."""

        with patch(
            "silvasonic.core.service_context.get_redis_connection",
            new_callable=AsyncMock,
        ) as mock_conn:
            mock_conn.return_value = None
            svc = _ConfigSvc()
            await svc._setup()

        assert config_called == [True]

    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    async def test_load_config_exception_does_not_abort_setup(
        self,
        mock_rc: MagicMock,
        mock_log: MagicMock,
        mock_hs: MagicMock,
    ) -> None:
        """A failing load_config() only logs a warning — setup continues."""
        from silvasonic.core.service import SilvaService

        class _BrokenConfigSvc(SilvaService):
            service_name = "broken"
            service_port = 19995

            async def load_config(self) -> None:
                raise ConnectionError("db unreachable")

            async def run(self) -> None:
                """No-op."""

        with patch(
            "silvasonic.core.service_context.get_redis_connection",
            new_callable=AsyncMock,
        ) as mock_conn:
            mock_conn.return_value = None
            svc = _BrokenConfigSvc()
            await svc._setup()

    def test_get_extra_meta_returns_empty_dict(self) -> None:
        """Default get_extra_meta returns an empty dict."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        assert svc.get_extra_meta() == {}

    def test_health_property_delegates_to_ctx(self) -> None:
        """The health property returns the HealthMonitor from ServiceContext."""
        from silvasonic.core.service import SilvaService

        svc = SilvaService()
        assert svc.health is svc._ctx.health


@pytest.mark.unit
class TestSilvaServiceLifecycle:
    """Tests for SilvaService._main lifecycle."""

    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    @patch(
        "silvasonic.core.service_context.get_redis_connection",
        new_callable=AsyncMock,
    )
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
                self._shutdown_event.set()

        svc = _QuickSvc()
        await svc._main()

    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    @patch(
        "silvasonic.core.service_context.get_redis_connection",
        new_callable=AsyncMock,
    )
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

    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    @patch(
        "silvasonic.core.service_context.get_redis_connection",
        new_callable=AsyncMock,
    )
    async def test_main_cancelled_error_on_signal(
        self,
        mock_redis: AsyncMock,
        mock_rc: MagicMock,
        mock_log: MagicMock,
        mock_hs: MagicMock,
    ) -> None:
        """_main: signal triggers CancelledError path."""
        from silvasonic.core.service import SilvaService

        mock_redis.return_value = None

        class _BlockingSvc(SilvaService):
            service_name = "blocker"
            service_port = 19988

            async def run(self) -> None:
                await asyncio.sleep(3600)

        svc = _BlockingSvc()

        async def cancel_after_start() -> None:
            while svc._run_task is None:
                await asyncio.sleep(0.01)
            svc._handle_signal(signal.SIGTERM)

        _signal_task = asyncio.create_task(cancel_after_start())
        await svc._main()
        assert svc._shutdown_event.is_set()
        assert _signal_task.done()


# ===================================================================
# Config Schemas
# ===================================================================


@pytest.mark.unit
class TestConfigSchemas:
    """Tests for Pydantic configuration schemas."""

    def test_system_settings_defaults(self) -> None:
        """SystemSettings has correct defaults."""
        s = SystemSettings()
        assert s.latitude == 53.55
        assert s.longitude == 9.99
        assert s.max_recorders == 5
        assert s.station_name == "Silvasonic MVP"

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
        assert s.janitor_batch_size == 50
        assert s.indexer_poll_interval == 2.0

    def test_uploader_settings_defaults(self) -> None:
        """UploaderSettings has correct defaults."""
        s = UploaderSettings()
        assert s.enabled is True
        assert s.bandwidth_limit == "1M"
        assert s.schedule_start_hour is None
        assert s.schedule_end_hour is None

    def test_system_settings_override(self) -> None:
        """SystemSettings accepts overrides."""
        s = SystemSettings(latitude=48.13, longitude=11.58, station_name="München")
        assert s.latitude == 48.13
        assert s.station_name == "München"


# ===================================================================
# Lazy DB Session
# ===================================================================


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
        mock_engine.assert_called_once()

        session._get_engine.cache_clear()
        session._get_session_factory.cache_clear()
