"""Redis Pub/Sub nudge subscriber (ADR-0017, messaging_patterns.md §6).

Listens to the ``silvasonic:nudge`` Redis channel and triggers
the reconciliation loop when a ``"reconcile"`` message is received.

The nudge is a simple wake-up signal — not a command. If the subscriber
is down or the message is lost, the reconciliation timer catches up.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, NoReturn

import structlog
from silvasonic.core.constants import RECONNECT_DELAY_S

if TYPE_CHECKING:
    from silvasonic.controller.controller_stats import ControllerStats
    from silvasonic.controller.reconciler import ReconciliationLoop

log = structlog.get_logger()

# Redis channel name (ADR-0017)
NUDGE_CHANNEL = "silvasonic:nudge"


class NudgeSubscriber:
    """Subscribe to Redis ``silvasonic:nudge`` and trigger reconciliation.

    Uses ``redis-py`` async Pub/Sub. Resilient to Redis disconnections —
    reconnects automatically with exponential backoff.
    """

    def __init__(
        self,
        reconciler: ReconciliationLoop,
        redis_url: str = "redis://localhost:6379/0",
    ) -> None:
        """Initialize with a ReconciliationLoop and Redis URL."""
        self._reconciler = reconciler
        self._redis_url = redis_url
        self._stats: ControllerStats | None = None

    def set_stats(self, stats: ControllerStats) -> None:
        """Wire a ControllerStats instance for nudge counting."""
        self._stats = stats

    def _handle_message(self, raw: dict[str, object]) -> None:
        """Process a single Pub/Sub message.

        Only ``"reconcile"`` payloads on ``"message"`` type trigger
        the reconciliation loop.  All other messages are ignored.
        """
        if raw["type"] != "message":
            return

        data = raw.get("data", b"")
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")

        log.debug("nudge_subscriber.received", payload=data)

        if data == "reconcile":
            self._reconciler.trigger()
            if self._stats is not None:
                self._stats.record_nudge()

    async def run(self) -> NoReturn:
        """Listen for nudge messages and trigger reconciliation.

        Automatically reconnects on disconnection with 5s delay.
        """
        import redis.asyncio as aioredis

        while True:  # pragma: no cover — integration-tested (test_nudge_subscriber.py)
            client = None
            try:
                client = aioredis.from_url(self._redis_url)
                pubsub = client.pubsub()
                await pubsub.subscribe(NUDGE_CHANNEL)
                log.info("nudge_subscriber.connected", channel=NUDGE_CHANNEL)

                async for message in pubsub.listen():
                    self._handle_message(message)

            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("nudge_subscriber.disconnected", reconnect_in=RECONNECT_DELAY_S)
                await asyncio.sleep(RECONNECT_DELAY_S)
            finally:
                if client is not None:
                    await client.aclose()
