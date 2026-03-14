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

if TYPE_CHECKING:
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

        log.info("nudge_subscriber.received", payload=data)

        if data == "reconcile":
            self._reconciler.trigger()

    async def run(self) -> NoReturn:
        """Listen for nudge messages and trigger reconciliation.

        Automatically reconnects on disconnection with 5s delay.
        """
        import redis.asyncio as aioredis

        while True:
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
                log.warning("nudge_subscriber.disconnected", reconnect_in=5)
                await asyncio.sleep(5)
            finally:
                if client is not None:
                    await client.aclose()
