"""Unit tests for SilvaService, ConfigSchemas, and lazy DB sessions.

Covers the SilvaService base class lifecycle (_setup, _main, _teardown),
signal handling, dying-gasp, load_config hook, get_extra_meta, health
property, settings section schemas (Station/Recording/Storage/Sync/Birdnet), and lazy
session initialization.
"""

import asyncio
import signal
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from silvasonic.core.schemas.settings import (
    BirdnetSettings,
    RecordingSettings,
    StationSettings,
    StorageSettings,
    SyncSettings,
    TimeWindow,
)

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
    """Tests for Pydantic settings section schemas."""

    def test_station_settings_defaults(self) -> None:
        """StationSettings has correct defaults; the id is generated by the seeder."""
        s = StationSettings()
        assert s.id is None
        assert s.latitude is None
        assert s.longitude is None
        assert s.name == "Silvasonic MVP"

    def test_recording_settings_defaults(self) -> None:
        """RecordingSettings has correct defaults."""
        s = RecordingSettings()
        assert s.auto_enrollment is True
        assert s.max_microphones == 5

    def test_birdnet_settings_defaults(self) -> None:
        """BirdnetSettings has correct defaults."""
        s = BirdnetSettings()
        assert s.min_confidence == 0.65
        assert s.clip_padding_s == 3.0
        assert s.overlap_s == 0.0
        assert s.sensitivity == 1.0
        assert s.thread_count == 1
        assert s.processing_order == "oldest_first"

    def test_storage_settings_defaults(self) -> None:
        """StorageSettings has correct defaults."""
        s = StorageSettings()
        assert s.warning_percent == 70.0
        assert s.critical_percent == 80.0
        assert s.emergency_percent == 90.0
        assert s.cleanup_interval_s == 60
        assert s.cleanup_batch_files == 50
        assert s.index_interval_s == 2.0

    def test_sync_settings_defaults(self) -> None:
        """SyncSettings has correct defaults; the switch lives in modules."""
        s = SyncSettings()
        assert "enabled" not in SyncSettings.model_fields
        assert s.poll_interval_s == 30
        assert s.bandwidth_limit_bytes_per_s == 1_048_576
        assert s.window is None

    def test_sync_settings_window(self) -> None:
        """A window parses from a plain dict."""
        s = SyncSettings.model_validate({"window": {"start": "22:00", "end": "06:00"}})
        assert s.window == TimeWindow(start="22:00", end="06:00")

    def test_station_settings_override(self) -> None:
        """StationSettings accepts overrides and serialises the id as a string."""
        station_id = uuid.UUID("0193f1c2-7b3a-7c4e-9d55-0a1b2c3d4e5f")
        s = StationSettings(id=station_id, latitude=48.13, longitude=11.58, name="München")
        assert s.latitude == 48.13
        assert s.name == "München"
        assert s.model_dump(mode="json")["id"] == str(station_id)


@pytest.mark.unit
class TestTimeWindow:
    """TimeWindow accepts HH:MM (24 h) only."""

    @pytest.mark.parametrize("value", ["00:00", "06:30", "23:59"])
    def test_valid(self, value: str) -> None:
        """Wall-clock times within a day pass."""
        assert TimeWindow(start=value, end=value).start == value

    @pytest.mark.parametrize("value", ["24:00", "6:30", "12:60", "12-30", "", "12:30:00"])
    def test_invalid(self, value: str) -> None:
        """Anything else is rejected."""
        with pytest.raises(ValidationError):
            TimeWindow(start=value, end="06:00")


# ===================================================================
# Snapshot Refresh (_refresh_config)
# ===================================================================


@pytest.mark.unit
class TestRefreshConfig:
    """Tests for SilvaService._refresh_config() staleness check (ADR-0031).

    Covers four behavioral branches:
    1. Short-circuit when no settings sections are declared.
    2. No-op when timestamps haven't changed (staleness cache hit).
    3. Calls load_config() when timestamps indicate a change.
    4. Swallows DB errors and keeps the previous configuration.
    """

    async def test_no_config_sections_returns_immediately(self) -> None:
        """Services without _config_sections skip the DB query entirely."""
        svc_cls = _make_test_service()
        svc = svc_cls()

        assert svc._config_sections == []

        # If it tried to hit the DB, it would raise (no session configured).
        # The fact that it completes means the short-circuit works.
        await svc._refresh_config()

    async def test_unchanged_timestamps_skip_load_config(self) -> None:
        """When updated_at hasn't changed, load_config() is NOT called."""
        from datetime import UTC, datetime

        svc_cls = _make_test_service()
        svc = svc_cls()
        svc._config_sections = ["test_section"]

        frozen_time = datetime(2026, 1, 1, tzinfo=UTC)

        # Pre-seed the cache to simulate a previous successful refresh
        svc._config_updated_at = {"test_section": frozen_time}

        # Mock: DB returns the SAME timestamp
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [("test_section", frozen_time)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        svc.load_config = AsyncMock()

        with patch(
            "silvasonic.core.database.session.get_session",
            return_value=mock_ctx,
        ):
            await svc._refresh_config()

        # load_config should NOT have been called — timestamps identical
        svc.load_config.assert_not_awaited()

    async def test_newer_timestamp_triggers_load_config(self) -> None:
        """When updated_at is newer than cached, load_config() IS called."""
        from datetime import UTC, datetime, timedelta

        svc_cls = _make_test_service()
        svc = svc_cls()
        svc._config_sections = ["test_section"]

        old_time = datetime(2026, 1, 1, tzinfo=UTC)
        new_time = old_time + timedelta(seconds=5)

        # Pre-seed the cache with old timestamp
        svc._config_updated_at = {"test_section": old_time}

        # Mock: DB returns a NEWER timestamp
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [("test_section", new_time)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        svc.load_config = AsyncMock()

        with patch(
            "silvasonic.core.database.session.get_session",
            return_value=mock_ctx,
        ):
            await svc._refresh_config()

        # load_config MUST have been called — timestamp was newer
        svc.load_config.assert_awaited_once()
        # Cache must be updated to new timestamp
        assert svc._config_updated_at["test_section"] == new_time

    async def test_first_refresh_always_triggers_load_config(self) -> None:
        """On first call (empty cache), load_config() is always called."""
        from datetime import UTC, datetime

        svc_cls = _make_test_service()
        svc = svc_cls()
        svc._config_sections = ["section_a", "section_b"]

        now = datetime(2026, 4, 11, tzinfo=UTC)

        # Cache is empty — first time
        assert svc._config_updated_at == {}

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [("section_a", now), ("section_b", now)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        svc.load_config = AsyncMock()

        with patch(
            "silvasonic.core.database.session.get_session",
            return_value=mock_ctx,
        ):
            await svc._refresh_config()

        svc.load_config.assert_awaited_once()
        assert len(svc._config_updated_at) == 2

    async def test_db_error_swallowed_keeps_old_config(self) -> None:
        """DB errors are logged but don't crash — old config persists."""
        svc_cls = _make_test_service()
        svc = svc_cls()
        svc._config_sections = ["test_section"]
        svc.load_config = AsyncMock()

        # Simulate DB unreachable
        with patch(
            "silvasonic.core.database.session.get_session",
            side_effect=ConnectionError("db down"),
        ):
            # Must NOT raise
            await svc._refresh_config()

        # load_config should not have been called
        svc.load_config.assert_not_awaited()


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
