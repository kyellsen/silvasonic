"""Unit tests for NudgeSubscriber messaging and error handling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.controller.nudge_subscriber import NudgeSubscriber
from silvasonic.core.constants import RECONNECT_DELAY_S


@pytest.mark.unit
class TestNudgeSubscriberMessageHandling:
    """Tests for individual message processing via _handle_message."""

    def test_init(self) -> None:
        """NudgeSubscriber initializes with reconciler and redis_url."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler, redis_url="redis://test:6379/0")
        assert sub._redis_url == "redis://test:6379/0"
        assert sub._reconciler is reconciler

    def test_ignores_non_message_types(self) -> None:
        """Messages that are not type 'message' are ignored."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)

        sub._handle_message({"type": "subscribe", "data": 1})
        reconciler.trigger.assert_not_called()

    def test_triggers_reconcile_on_match(self) -> None:
        """Payload 'reconcile' triggers the reconciler."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)

        sub._handle_message({"type": "message", "data": b"reconcile"})
        reconciler.trigger.assert_called_once()

    def test_ignores_other_payloads(self) -> None:
        """Payloads other than 'reconcile' are ignored."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)

        sub._handle_message({"type": "message", "data": "restart"})
        reconciler.trigger.assert_not_called()

    def test_records_nudge_stats_if_wired(self) -> None:
        """Stats are incremented if a ControllerStats object is provided."""
        reconciler = MagicMock()
        stats = MagicMock()
        sub = NudgeSubscriber(reconciler)
        sub.set_stats(stats)

        sub._handle_message({"type": "message", "data": "reconcile"})
        stats.record_nudge.assert_called_once()
        reconciler.trigger.assert_called_once()

    def test_handle_string_data(self) -> None:
        """_handle_message() handles string data (not bytes)."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler)

        sub._handle_message({"type": "message", "data": "reconcile"})
        reconciler.trigger.assert_called_once()


@pytest.mark.unit
class TestNudgeSubscriberRun:
    """Tests for the NudgeSubscriber main loop and error recovery."""

    async def test_run_reconnects_on_error(self) -> None:
        """Exceptions in run() trigger a reconnect with the centralized delay."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler, redis_url="redis://fake:6379/0")

        call_count = 0

        def mock_from_url(*_args: object, **_kwargs: object) -> AsyncMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Simulate a connection error on first loop
                raise ConnectionError("Redis down")
            # Break the loop on the second try
            raise asyncio.CancelledError

        with (
            patch("redis.asyncio.from_url", side_effect=mock_from_url),
            patch(
                "silvasonic.controller.nudge_subscriber.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
            pytest.raises(asyncio.CancelledError),
        ):
            await sub.run()

        # After the first ConnectionError, it should catch, sleep, and try again
        mock_sleep.assert_called_once_with(RECONNECT_DELAY_S)

    async def test_run_closes_redis_in_finally(self) -> None:
        """Redis connection is closed correctly in the finally block."""
        reconciler = MagicMock()
        sub = NudgeSubscriber(reconciler, redis_url="redis://fake:6379/0")

        mock_client = MagicMock()
        mock_client.aclose = AsyncMock()
        # Mock pubsub().subscribe() to raise CancelledError so it gracefully exits
        # the try block but executes the finally block on the acquired client.
        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock(side_effect=asyncio.CancelledError)
        mock_client.pubsub.return_value = mock_pubsub

        with (
            patch("redis.asyncio.from_url", return_value=mock_client),
            pytest.raises(asyncio.CancelledError),
        ):
            await sub.run()

        mock_client.aclose.assert_awaited_once()
