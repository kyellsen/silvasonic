r"""SilvaService — Unified service base class (ADR-0019).

Every Silvasonic **background worker** inherits from ``SilvaService`` to get
the full managed lifecycle.  HTTP services (Web-Interface) use
:class:`~silvasonic.core.service_context.ServiceContext` directly via a
FastAPI ``lifespan`` — they do **not** subclass ``SilvaService``.

Both share the same infrastructure via ``ServiceContext``:

*   Structured logging (``structlog``)
*   Health monitoring (HTTP ``/healthy`` endpoint)
*   Liveness watchdog — ``health.touch()`` keeps the HTTP probe alive
*   Heartbeat publishing (Redis Pub/Sub ``silvasonic:status``)
*   Per-process resource monitoring (``psutil``)
*   Graceful shutdown (SIGTERM / SIGINT) with **immediate task cancellation**
*   Dying-gasp error heartbeat — last Redis publish on unexpected crash
*   Optional DB config loading via ``load_config()`` hook

Usage::

    class RecorderService(SilvaService):
        service_name = \"recorder\"
        service_port = 9500

        async def load_config(self) -> None:
            # Optional: read settings from system_config table
            async with get_session() as session:
                ...

        async def run(self) -> None:
            self.health.update_status(\"recording\", True, \"running\")
            while not self._shutdown_event.is_set():
                self.health.touch()   # keep watchdog happy
                await asyncio.sleep(1)

    if __name__ == \"__main__\":
        RecorderService().start()
"""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from typing import Any

import structlog
from silvasonic.core.health import HealthMonitor
from silvasonic.core.service_context import ServiceContext

logger = structlog.get_logger()


class SilvaService:
    """Base class for all Silvasonic **background worker** services.

    Delegates all infrastructure concerns (logging, health, heartbeat, Redis)
    to :class:`~silvasonic.core.service_context.ServiceContext`.

    Subclass this and implement :meth:`run` with your service logic.
    Call :meth:`start` to boot the full lifecycle.

    Class Attributes:
        service_name: Canonical name (e.g. ``recorder``, ``controller``).
        service_port: TCP port for the ``/healthy`` endpoint.

    Args:
        instance_id: Unique instance identifier (default: ``"default"``).
        workspace_path: Optional path for storage monitoring.
        redis_url: Redis connection URL.
        heartbeat_interval: Seconds between heartbeat publishes.
    """

    service_name: str = "unknown"
    service_port: int = 9000

    def __init__(
        self,
        instance_id: str = "default",
        workspace_path: str | Path | None = None,
        redis_url: str = "redis://localhost:6379/0",
        heartbeat_interval: float = 10.0,
    ) -> None:
        """Initialize the service."""
        self._ctx = ServiceContext(
            service_name=self.service_name,
            service_port=self.service_port,
            instance_id=instance_id,
            workspace_path=workspace_path,
            redis_url=redis_url,
            heartbeat_interval=heartbeat_interval,
        )
        self._shutdown_event = asyncio.Event()
        # Stored in _main() after run() task is created; used for active cancel.
        self._run_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Delegated properties — preserve backwards-compatible surface area
    # ------------------------------------------------------------------

    @property
    def health(self) -> HealthMonitor:
        """The shared HealthMonitor instance."""
        return self._ctx.health

    # ------------------------------------------------------------------
    # Subclass API (override these)
    # ------------------------------------------------------------------

    async def run(self) -> None:
        r"""Override this with your service logic.

        This coroutine runs after all infrastructure (health server,
        heartbeat, logging) is initialized.  It should run until
        ``self._shutdown_event`` is set.

        Call ``self.health.touch()`` on each main-loop iteration to keep
        the liveness watchdog alive.

        Example::

            async def run(self) -> None:
                self.health.update_status(\"main\", True)
                while not self._shutdown_event.is_set():
                    self.health.touch()
                    await asyncio.sleep(1)
        """
        raise NotImplementedError("Subclasses must implement run()")

    def get_extra_meta(self) -> dict[str, Any]:
        """Override to add service-specific fields to heartbeat meta.

        Returns:
            Dict merged into ``meta`` alongside ``resources``.
        """
        return {}

    async def load_config(self) -> None:
        """Override to load service configuration from the database.

        Called once during ``_setup()``, before ``run()``.  The default
        implementation is a no-op — services that do not need DB-based
        configuration do not have to override this.

        Best-effort: if the database is unreachable, ``_setup()`` logs a
        warning and continues — the service starts with hardcoded defaults.
        """

    # ------------------------------------------------------------------
    # Internal lifecycle helpers
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        """Initialize all infrastructure via ServiceContext, then load config."""
        await self._ctx.setup()

        # Register meta provider after setup (heartbeat exists only after setup)
        self._ctx.set_meta_provider(self.get_extra_meta)

        # DB config loading — best-effort
        try:
            await self.load_config()
        except Exception as exc:
            logger.warning("load_config_failed", error=str(exc))

    async def _teardown(self) -> None:
        """Gracefully shut down all infrastructure via ServiceContext."""
        await self._ctx.teardown()

    async def _publish_dying_gasp(self, exc: Exception) -> None:
        """Publish a final error heartbeat before crashing (Fix #3).

        Best-effort — any failure here is silently swallowed so as not to
        mask the original exception.
        """
        await self._ctx.publish_dying_gasp(exc)

    def _handle_signal(self, sig: signal.Signals) -> None:
        """Handle SIGTERM/SIGINT for graceful shutdown (Fix #2).

        Sets the shutdown event AND actively cancels the running task so
        that any ``await asyncio.sleep(...)`` inside ``run()`` is
        interrupted immediately — instead of waiting for the sleep to
        expire before detecting the shutdown event.
        """
        logger.info("signal_received", signal=sig.name)
        self._shutdown_event.set()
        run_task = self._run_task
        if run_task is not None and not run_task.done():
            run_task.cancel()

    async def _main(self) -> None:
        """Full service lifecycle: setup → run → teardown."""
        # Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal, sig)

        await self._setup()

        # Wrap run() in a Task so _handle_signal can cancel it (Fix #2)
        run_task = asyncio.create_task(self.run())
        self._run_task = run_task

        try:
            await run_task
        except asyncio.CancelledError:
            # Expected on graceful shutdown — not an error.
            pass
        except Exception as exc:
            # Unexpected crash — publish a dying-gasp heartbeat (Fix #3)
            logger.error(
                "service_crashed",
                service=self.service_name,
                error=str(exc),
                exc_info=True,
            )
            await self._publish_dying_gasp(exc)
            raise
        finally:
            await self._teardown()

    def start(self) -> None:
        """Boot the service. Blocks until shutdown.

        This is the main entry point — call this from ``__main__``.
        """
        asyncio.run(self._main())
