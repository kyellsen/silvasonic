"""ServiceContext — shared infrastructure lifecycle for all Silvasonic services.

This module solves the fundamental split between two service archetypes:

- **Background workers** (Recorder, Controller, BirdNET, …): use :class:`SilvaService`.
  ``SilvaService`` owns the ``asyncio`` event loop and calls ``_main()`` directly.

- **HTTP servers** (Web-Interface, Web-Mock, …): use FastAPI + Uvicorn.
  Uvicorn owns the event loop; service infrastructure hooks in via ``lifespan``.

Both archetypes share the **same infrastructure** (logging, health monitor,
heartbeat, Redis, resource collection) by composing :class:`ServiceContext`.

Usage in a FastAPI lifespan (HTTP services)::

    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from silvasonic.core.service_context import ServiceContext

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with ServiceContext(
            service_name="web-interface",
            service_port=8000,
        ) as ctx:
            app.state.ctx = ctx
            yield

    app = FastAPI(lifespan=lifespan)

Usage in a background worker (via :class:`~silvasonic.core.service.SilvaService`)::

    # SilvaService delegates _setup()/_teardown() to ServiceContext internally.
    # No change required in subclasses.

See Also:
    :mod:`silvasonic.core.service` — SilvaService base class.
    ADR-0019: Unified Service Infrastructure.
"""

from __future__ import annotations

from http.server import HTTPServer
from pathlib import Path
from types import TracebackType

import structlog
from silvasonic.core.health import HealthMonitor, start_health_server
from silvasonic.core.heartbeat import HeartbeatPublisher, MetaProvider
from silvasonic.core.logging import configure_logging
from silvasonic.core.redis import get_redis_connection
from silvasonic.core.resources import ResourceCollector

logger = structlog.get_logger()

_REDIS_DEFAULT = "redis://localhost:6379/0"


class ServiceContext:
    """Shared infrastructure for every Silvasonic service.

    Encapsulates the full setup/teardown sequence that is common to both
    background workers (:class:`~silvasonic.core.service.SilvaService`) and
    HTTP services (FastAPI ``lifespan``).

    Supports use as an async context manager for clean ``async with`` usage
    in FastAPI lifespans.

    Args:
        service_name: Canonical service name (e.g. ``"web-interface"``).
        service_port: TCP port for the ``/healthy`` endpoint.
        instance_id: Unique instance identifier (default ``"default"``).
        workspace_path: Optional path for NVMe storage monitoring.
        redis_url: Redis connection URL.
        heartbeat_interval: Seconds between heartbeat publishes.
    """

    def __init__(
        self,
        service_name: str,
        service_port: int,
        instance_id: str = "default",
        workspace_path: str | Path | None = None,
        redis_url: str = _REDIS_DEFAULT,
        heartbeat_interval: float = 10.0,
        skip_health_server: bool = False,
    ) -> None:
        """Initialize the service context (does not connect yet — call setup())."""
        self.service_name = service_name
        self.service_port = service_port
        self.instance_id = instance_id
        self.workspace_path = workspace_path
        self.redis_url = redis_url
        self.heartbeat_interval = heartbeat_interval
        self.skip_health_server = skip_health_server

        # Populated during setup()
        self.health: HealthMonitor = HealthMonitor()
        self._resource_collector: ResourceCollector | None = None
        self._heartbeat: HeartbeatPublisher | None = None
        self._health_server: HTTPServer | None = None

    # ------------------------------------------------------------------
    # Public properties (for tests and external observers)
    # ------------------------------------------------------------------

    @property
    def heartbeat(self) -> HeartbeatPublisher | None:
        """The active HeartbeatPublisher, or None if Redis is unavailable."""
        return self._heartbeat

    @heartbeat.setter
    def heartbeat(self, value: HeartbeatPublisher | None) -> None:
        """Allow tests to inject a mock heartbeat publisher."""
        self._heartbeat = value

    @property
    def resource_collector(self) -> ResourceCollector | None:
        """The active ResourceCollector, or None before setup."""
        return self._resource_collector

    @resource_collector.setter
    def resource_collector(self, value: ResourceCollector | None) -> None:
        """Allow tests to inject a mock resource collector."""
        self._resource_collector = value

    # ------------------------------------------------------------------
    # Public lifecycle API
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """Initialize all infrastructure: logging, health, Redis, heartbeat.

        Idempotent with respect to logging and health server (both are
        module-level singletons).  Safe to call once per process start.
        """
        # 1. Structured logging
        configure_logging(self.service_name)
        logger.info(
            "service_starting",
            service=self.service_name,
            instance_id=self.instance_id,
            port=self.service_port,
        )

        # 2. HTTP /healthy endpoint — skip for HTTP services (Uvicorn/FastAPI
        #    already owns the port and serves /healthy natively).
        if not self.skip_health_server:
            self._health_server = start_health_server(port=self.service_port, monitor=self.health)
        self.health.update_status("init", True, "starting up")

        # 3. Per-process resource monitoring (CPU, memory, optional NVMe)
        self._resource_collector = ResourceCollector(workspace_path=self.workspace_path)

        # 4. Redis + Heartbeat — best-effort (skipped if Redis unavailable)
        redis = await get_redis_connection(self.redis_url)
        if redis is not None:
            self._heartbeat = HeartbeatPublisher(
                redis=redis,
                service_name=self.service_name,
                instance_id=self.instance_id,
                interval=self.heartbeat_interval,
            )
            self._heartbeat.set_health_provider(self.health.get_status)
            self._heartbeat.start(self._resource_collector)
        else:
            logger.warning("heartbeat_disabled", reason="redis_unavailable")

        logger.info("service_infrastructure_ready", service=self.service_name)

    async def teardown(self) -> None:
        """Gracefully shut down all infrastructure (heartbeat, Redis)."""
        logger.info("service_shutting_down", service=self.service_name)
        if self._health_server is not None:
            self._health_server.shutdown()
        if self._heartbeat:
            await self._heartbeat.stop()
        logger.info("service_stopped", service=self.service_name)

    async def publish_dying_gasp(self, exc: Exception) -> None:
        """Publish a final error heartbeat before an unexpected crash.

        Best-effort — failures here are silently ignored so as not to mask
        the original exception.

        Args:
            exc: The exception that caused the crash.
        """
        if self._heartbeat is None or self._resource_collector is None:
            return
        try:
            self.health.update_status("service", False, f"crash: {exc!r}")
            resources = self._resource_collector.collect()
            await self._heartbeat.publish_once(resources)
        except Exception:
            logger.debug("dying_gasp_failed", exc_info=True)

    def set_meta_provider(self, fn: MetaProvider) -> None:
        """Register a callable that returns service-specific heartbeat meta.

        Args:
            fn: Callable ``() -> dict[str, Any]``.
        """
        if self._heartbeat is not None:
            self._heartbeat.set_meta_provider(fn)

    # ------------------------------------------------------------------
    # Async context manager — for FastAPI lifespan and tests
    # ------------------------------------------------------------------

    async def __aenter__(self) -> ServiceContext:
        """Async context manager entry — calls setup()."""
        await self.setup()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Async context manager exit — calls teardown()."""
        await self.teardown()
