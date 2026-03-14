"""Unit tests for silvasonic.core.service_context module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.heartbeat import DEFAULT_HEARTBEAT_INTERVAL_S
from silvasonic.core.service_context import ServiceContext


@pytest.mark.unit
class TestServiceContextInit:
    """Tests for ServiceContext initialization."""

    def test_stores_parameters(self) -> None:
        """All constructor args are stored on the instance."""
        ctx = ServiceContext(
            service_name="test",
            service_port=9999,
            instance_id="inst-01",
            workspace_path="/data",
            redis_url="redis://redis:6379/1",
            heartbeat_interval=DEFAULT_HEARTBEAT_INTERVAL_S,
            skip_health_server=True,
        )
        assert ctx.service_name == "test"
        assert ctx.service_port == 9999
        assert ctx.instance_id == "inst-01"
        assert ctx.workspace_path == "/data"
        assert ctx.redis_url == "redis://redis:6379/1"
        assert ctx.heartbeat_interval == DEFAULT_HEARTBEAT_INTERVAL_S
        assert ctx.skip_health_server is True

    def test_defaults(self) -> None:
        """Default values for optional parameters."""
        ctx = ServiceContext(service_name="svc", service_port=8000)
        assert ctx.instance_id == "default"
        assert ctx.workspace_path is None
        assert ctx.heartbeat_interval == DEFAULT_HEARTBEAT_INTERVAL_S
        assert ctx.skip_health_server is False

    def test_heartbeat_initially_none(self) -> None:
        """Heartbeat is None before setup() is called."""
        ctx = ServiceContext(service_name="svc", service_port=8000)
        assert ctx.heartbeat is None

    def test_resource_collector_initially_none(self) -> None:
        """Resource collector is None before setup() is called."""
        ctx = ServiceContext(service_name="svc", service_port=8000)
        assert ctx.resource_collector is None


@pytest.mark.unit
class TestServiceContextSetup:
    """Tests for ServiceContext.setup()."""

    @pytest.mark.asyncio
    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    @patch("silvasonic.core.service_context.get_redis_connection", new_callable=AsyncMock)
    async def test_setup_with_redis(
        self,
        mock_redis: AsyncMock,
        mock_rc: MagicMock,
        mock_logging: MagicMock,
        mock_health_srv: MagicMock,
    ) -> None:
        """Setup creates heartbeat when Redis is available."""
        mock_redis.return_value = AsyncMock()

        ctx = ServiceContext(service_name="test", service_port=9999)
        await ctx.setup()

        mock_logging.assert_called_once_with("test")
        mock_health_srv.assert_called_once()
        assert ctx.heartbeat is not None
        assert ctx.resource_collector is not None

        # Cleanup
        await ctx.teardown()

    @pytest.mark.asyncio
    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    @patch("silvasonic.core.service_context.get_redis_connection", new_callable=AsyncMock)
    async def test_setup_without_redis(
        self,
        mock_redis: AsyncMock,
        mock_rc: MagicMock,
        mock_logging: MagicMock,
        mock_health_srv: MagicMock,
    ) -> None:
        """Setup degrades gracefully when Redis is unavailable."""
        mock_redis.return_value = None

        ctx = ServiceContext(service_name="test", service_port=9999)
        await ctx.setup()

        assert ctx.heartbeat is None
        assert ctx.resource_collector is not None

    @pytest.mark.asyncio
    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    @patch("silvasonic.core.service_context.get_redis_connection", new_callable=AsyncMock)
    async def test_setup_skips_health_server(
        self,
        mock_redis: AsyncMock,
        mock_rc: MagicMock,
        mock_logging: MagicMock,
        mock_health_srv: MagicMock,
    ) -> None:
        """skip_health_server=True prevents start_health_server from being called."""
        mock_redis.return_value = None

        ctx = ServiceContext(service_name="web", service_port=8000, skip_health_server=True)
        await ctx.setup()

        mock_health_srv.assert_not_called()


@pytest.mark.unit
class TestServiceContextTeardown:
    """Tests for ServiceContext.teardown()."""

    @pytest.mark.asyncio
    async def test_teardown_stops_heartbeat(self) -> None:
        """teardown() calls heartbeat.stop() when heartbeat is present."""
        ctx = ServiceContext(service_name="test", service_port=9999)
        mock_hb = AsyncMock()
        ctx.heartbeat = mock_hb

        await ctx.teardown()

        mock_hb.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_teardown_without_heartbeat(self) -> None:
        """teardown() is safe when heartbeat is None."""
        ctx = ServiceContext(service_name="test", service_port=9999)
        ctx.heartbeat = None

        # Must not raise
        await ctx.teardown()


@pytest.mark.unit
class TestServiceContextDyingGasp:
    """Tests for ServiceContext.publish_dying_gasp()."""

    @pytest.mark.asyncio
    async def test_publishes_when_heartbeat_present(self) -> None:
        """publish_dying_gasp calls publish_once and reports error status."""
        ctx = ServiceContext(service_name="test", service_port=9999)
        mock_hb = AsyncMock()
        mock_rc = MagicMock()
        mock_rc.collect.return_value = {"cpu_percent": 1.0}
        ctx.heartbeat = mock_hb
        ctx.resource_collector = mock_rc

        await ctx.publish_dying_gasp(RuntimeError("boom"))

        mock_hb.publish_once.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_silent_when_no_heartbeat(self) -> None:
        """Does nothing if heartbeat is None."""
        ctx = ServiceContext(service_name="test", service_port=9999)
        ctx.heartbeat = None
        ctx.resource_collector = None

        # Must not raise
        await ctx.publish_dying_gasp(RuntimeError("no redis"))

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self) -> None:
        """Exceptions during dying gasp are silently swallowed."""
        ctx = ServiceContext(service_name="test", service_port=9999)
        mock_hb = AsyncMock()
        mock_hb.publish_once.side_effect = ConnectionError("redis gone")
        mock_rc = MagicMock()
        mock_rc.collect.return_value = {}
        ctx.heartbeat = mock_hb
        ctx.resource_collector = mock_rc

        # Must not raise
        await ctx.publish_dying_gasp(RuntimeError("crash"))


@pytest.mark.unit
class TestServiceContextMetaProvider:
    """Tests for ServiceContext.set_meta_provider()."""

    def test_delegates_to_heartbeat(self) -> None:
        """set_meta_provider forwards to heartbeat when present."""
        ctx = ServiceContext(service_name="test", service_port=9999)
        mock_hb = MagicMock()
        ctx.heartbeat = mock_hb
        fn = lambda: {"key": "value"}  # noqa: E731

        ctx.set_meta_provider(fn)

        mock_hb.set_meta_provider.assert_called_once_with(fn)

    def test_noop_when_no_heartbeat(self) -> None:
        """set_meta_provider does nothing when heartbeat is None."""
        ctx = ServiceContext(service_name="test", service_port=9999)
        ctx.heartbeat = None

        # Must not raise
        ctx.set_meta_provider(lambda: {})


@pytest.mark.unit
class TestServiceContextPropertySetters:
    """Tests for heartbeat and resource_collector property setters."""

    def test_heartbeat_setter(self) -> None:
        """Can inject a mock heartbeat via the setter."""
        ctx = ServiceContext(service_name="test", service_port=9999)
        mock = MagicMock()
        ctx.heartbeat = mock
        assert ctx.heartbeat is mock

    def test_resource_collector_setter(self) -> None:
        """Can inject a mock resource_collector via the setter."""
        ctx = ServiceContext(service_name="test", service_port=9999)
        mock = MagicMock()
        ctx.resource_collector = mock
        assert ctx.resource_collector is mock


@pytest.mark.unit
class TestServiceContextAsyncContextManager:
    """Tests for async context manager (__aenter__ / __aexit__)."""

    @pytest.mark.asyncio
    @patch("silvasonic.core.service_context.start_health_server")
    @patch("silvasonic.core.service_context.configure_logging")
    @patch("silvasonic.core.service_context.ResourceCollector")
    @patch("silvasonic.core.service_context.get_redis_connection", new_callable=AsyncMock)
    async def test_context_manager_calls_setup_and_teardown(
        self,
        mock_redis: AsyncMock,
        mock_rc: MagicMock,
        mock_logging: MagicMock,
        mock_health_srv: MagicMock,
    ) -> None:
        """__aenter__ calls setup(), __aexit__ calls teardown()."""
        mock_redis.return_value = None

        async with ServiceContext(service_name="ctx-test", service_port=9997) as ctx:
            assert isinstance(ctx, ServiceContext)
            mock_logging.assert_called_once_with("ctx-test")

        # After exiting, teardown should have been called — no error means pass
