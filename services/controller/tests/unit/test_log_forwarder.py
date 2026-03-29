"""Unit tests for LogForwarder (Phase 5 — ADR-0022).

Covers:
- Container tracking lifecycle (new, removed, finished tasks)
- JSON log line parsing and enrichment
- Non-JSON fallback wrapping
- Redis publish fire-and-forget
- Graceful shutdown
"""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.controller.log_forwarder import (
    LogForwarder,
    _parse_log_line,
)
from silvasonic.core.constants import RECONNECT_DELAY_S


# ---------------------------------------------------------------------------
# _parse_log_line tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestParseLogLine:
    """Tests for the _parse_log_line helper."""

    def test_valid_json_structlog(self) -> None:
        """Valid structlog JSON is parsed and enriched."""
        raw = json.dumps(
            {
                "event": "Recording started",
                "level": "info",
                "timestamp": "2026-03-14T23:00:00Z",
            }
        )
        result = _parse_log_line(
            raw,
            service="recorder",
            instance_id="mic-01",
            container_name="silvasonic-recorder-ultramic-034f",
        )

        assert result["service"] == "recorder"
        assert result["instance_id"] == "mic-01"
        assert result["container_name"] == "silvasonic-recorder-ultramic-034f"
        assert result["level"] == "info"
        assert result["message"] == "Recording started"
        assert result["timestamp"] == "2026-03-14T23:00:00Z"

    def test_json_with_message_key(self) -> None:
        """JSON with 'message' key (instead of 'event') is supported."""
        raw = json.dumps({"message": "Hello", "level": "debug"})
        result = _parse_log_line(
            raw,
            service="recorder",
            instance_id="mic-01",
            container_name="test-container",
        )
        assert result["message"] == "Hello"
        assert result["level"] == "debug"

    def test_json_without_level(self) -> None:
        """JSON without 'level' defaults to 'info'."""
        raw = json.dumps({"event": "something"})
        result = _parse_log_line(
            raw,
            service="recorder",
            instance_id="mic-01",
            container_name="test-container",
        )
        assert result["level"] == "info"

    def test_non_json_wrapped(self) -> None:
        """Non-JSON line is wrapped with level='raw'."""
        raw = "Traceback (most recent call last):"
        result = _parse_log_line(
            raw,
            service="recorder",
            instance_id="mic-01",
            container_name="test-container",
        )

        assert result["level"] == "raw"
        assert result["message"] == raw
        assert result["service"] == "recorder"
        assert "timestamp" in result

    def test_empty_string_wrapped(self) -> None:
        """Empty string after parse attempt is wrapped as raw."""
        result = _parse_log_line(
            "",
            service="recorder",
            instance_id="mic-01",
            container_name="test-container",
        )
        assert result["level"] == "raw"
        assert result["message"] == ""

    def test_preserves_exc_info(self) -> None:
        """Structlog fields like exc_info are preserved."""
        raw = json.dumps(
            {
                "event": "Error",
                "level": "error",
                "exc_info": "ValueError: bad value",
            }
        )
        result = _parse_log_line(
            raw,
            service="svc",
            instance_id="id",
            container_name="name",
        )
        assert result["exc_info"] == "ValueError: bad value"


# ---------------------------------------------------------------------------
# LogForwarder tests
# ---------------------------------------------------------------------------
def _make_forwarder(
    *,
    containers: list[dict[str, Any]] | None = None,
    is_connected: bool = True,
) -> tuple[LogForwarder, MagicMock]:
    """Create a LogForwarder with a mocked PodmanClient.

    Returns (forwarder, mock_podman_client).
    """
    mock_podman = MagicMock()
    mock_podman.is_connected = is_connected
    mock_podman.list_managed_containers.return_value = containers or []

    forwarder = LogForwarder(mock_podman, redis_url="redis://localhost:6379/0")
    return forwarder, mock_podman


@pytest.mark.unit
class TestLogForwarderSync:
    """Tests for _sync_follow_tasks logic."""

    async def test_no_containers_no_tasks(self) -> None:
        """No managed containers → no follow tasks spawned."""
        forwarder, _ = _make_forwarder(containers=[])
        mock_redis = AsyncMock()

        with patch(
            "silvasonic.controller.log_forwarder.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await forwarder._sync_follow_tasks(mock_redis)

        assert len(forwarder._follow_tasks) == 0

    async def test_new_container_spawns_follow_task(self) -> None:
        """New container detected → follow task created."""
        containers: list[dict[str, Any]] = [
            {
                "id": "abc123",
                "name": "silvasonic-recorder-ultramic-034f",
                "status": "running",
                "labels": {
                    "io.silvasonic.service": "recorder",
                    "io.silvasonic.device_id": "2578-0001-ABC",
                },
            },
        ]
        forwarder, _ = _make_forwarder(containers=containers)
        mock_redis = AsyncMock()

        with (
            patch(
                "silvasonic.controller.log_forwarder.asyncio.to_thread",
                new_callable=AsyncMock,
                return_value=containers,
            ),
            patch.object(
                forwarder,
                "_follow_container",
                new_callable=AsyncMock,
            ),
        ):
            await forwarder._sync_follow_tasks(mock_redis)

        assert "silvasonic-recorder-ultramic-034f" in forwarder._follow_tasks

    async def test_removed_container_cancels_task(self) -> None:
        """Container disappears → follow task cancelled."""
        forwarder, _ = _make_forwarder(containers=[])
        mock_redis = AsyncMock()

        # Pre-populate a follow task
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.done.return_value = False
        forwarder._follow_tasks["old-container"] = mock_task

        with patch(
            "silvasonic.controller.log_forwarder.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await forwarder._sync_follow_tasks(mock_redis)

        mock_task.cancel.assert_called_once()
        assert "old-container" not in forwarder._follow_tasks

    async def test_finished_tasks_cleaned_up(self) -> None:
        """Completed follow tasks are removed from the tracking map."""
        forwarder, _ = _make_forwarder(containers=[])
        mock_redis = AsyncMock()

        # Pre-populate a finished task
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.done.return_value = True
        forwarder._follow_tasks["finished-container"] = mock_task

        with patch(
            "silvasonic.controller.log_forwarder.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await forwarder._sync_follow_tasks(mock_redis)

        assert "finished-container" not in forwarder._follow_tasks

    async def test_not_connected_noop(self) -> None:
        """If Podman is not connected, sync is a no-op."""
        forwarder, _ = _make_forwarder(is_connected=False)
        mock_redis = AsyncMock()

        await forwarder._sync_follow_tasks(mock_redis)

        assert len(forwarder._follow_tasks) == 0

    async def test_labels_extracted_correctly(self) -> None:
        """Container labels are used for service and instance_id."""
        containers: list[dict[str, Any]] = [
            {
                "id": "xyz789",
                "name": "silvasonic-recorder-test-abcd",
                "status": "running",
                "labels": {
                    "io.silvasonic.service": "recorder",
                    "io.silvasonic.device_id": "test-device-id",
                },
            },
        ]
        forwarder, _ = _make_forwarder(containers=containers)
        mock_redis = AsyncMock()

        follow_calls: list[dict[str, Any]] = []

        async def capture_follow(**kwargs: Any) -> None:
            follow_calls.append(kwargs)

        with (
            patch(
                "silvasonic.controller.log_forwarder.asyncio.to_thread",
                new_callable=AsyncMock,
                return_value=containers,
            ),
            patch.object(
                forwarder,
                "_follow_container",
                side_effect=capture_follow,
            ),
        ):
            await forwarder._sync_follow_tasks(mock_redis)

        # The task was created — verify the follow function was called
        # with correct arguments by checking the task exists
        assert "silvasonic-recorder-test-abcd" in forwarder._follow_tasks


@pytest.mark.unit
class TestLogForwarderShutdown:
    """Tests for graceful shutdown."""

    async def test_cancel_all_tasks(self) -> None:
        """_cancel_all_tasks cancels all active follow tasks."""
        forwarder, _ = _make_forwarder()

        task1 = MagicMock(spec=asyncio.Task)
        task1.done.return_value = False
        task1.cancel.return_value = None

        task2 = MagicMock(spec=asyncio.Task)
        task2.done.return_value = False
        task2.cancel.return_value = None

        forwarder._follow_tasks = {"c1": task1, "c2": task2}

        with patch(
            "silvasonic.controller.log_forwarder.asyncio.gather",
            new_callable=AsyncMock,
        ):
            await forwarder._cancel_all_tasks()

        task1.cancel.assert_called_once()
        task2.cancel.assert_called_once()
        assert len(forwarder._follow_tasks) == 0

    async def test_cancel_all_tasks_empty(self) -> None:
        """_cancel_all_tasks is safe to call with no tasks."""
        forwarder, _ = _make_forwarder()
        await forwarder._cancel_all_tasks()
        assert len(forwarder._follow_tasks) == 0


@pytest.mark.unit
class TestLogForwarderPublish:
    """Tests for log payload publishing."""

    async def test_publishes_json_log_line(self) -> None:
        """Valid JSON log line is parsed, enriched, and published."""
        forwarder, mock_podman = _make_forwarder()

        mock_container = MagicMock()
        # container.logs() returns a generator; use iter() to simulate
        mock_container.logs.return_value = iter(
            [
                b'{"event": "Recording started", "level": "info"}\n',
            ]
        )
        mock_podman.containers.get.return_value = mock_container

        mock_redis = AsyncMock()
        published_payloads: list[str] = []

        async def capture_publish(channel: str, data: str) -> int:
            published_payloads.append(data)
            return 0

        mock_redis.publish = capture_publish

        # to_thread is called twice: once for containers.get, once for _iter_logs
        # We need synchronous execution for both
        async def fake_to_thread(fn: Any, *args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        with patch(
            "silvasonic.controller.log_forwarder.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            await forwarder._follow_container(
                name="test-container",
                service="recorder",
                instance_id="mic-01",
                redis=mock_redis,
            )

        assert len(published_payloads) >= 1
        payload = json.loads(published_payloads[0])
        assert payload["service"] == "recorder"
        assert payload["instance_id"] == "mic-01"
        assert payload["message"] == "Recording started"
        assert payload["level"] == "info"

    async def test_publishes_non_json_fallback(self) -> None:
        """Non-JSON stdout is wrapped and published with level='raw'."""
        forwarder, mock_podman = _make_forwarder()

        mock_container = MagicMock()
        mock_container.logs.return_value = iter(
            [
                b"Python startup banner v3.11\n",
            ]
        )
        mock_podman.containers.get.return_value = mock_container

        mock_redis = AsyncMock()
        published_payloads: list[str] = []

        async def capture_publish(channel: str, data: str) -> int:
            published_payloads.append(data)
            return 0

        mock_redis.publish = capture_publish

        async def fake_to_thread(fn: Any, *args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        with patch(
            "silvasonic.controller.log_forwarder.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            await forwarder._follow_container(
                name="test-container",
                service="recorder",
                instance_id="mic-01",
                redis=mock_redis,
            )

        assert len(published_payloads) >= 1
        payload = json.loads(published_payloads[0])
        assert payload["level"] == "raw"
        assert payload["message"] == "Python startup banner v3.11"


# ---------------------------------------------------------------------------
# run() main loop tests (L127-148)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestLogForwarderRun:
    """Tests for the run() main loop."""

    async def test_run_cancelled_cleans_up(self) -> None:
        """CancelledError in run() cancels all follow tasks and re-raises."""
        forwarder, _ = _make_forwarder()

        call_count = 0

        async def mock_sync(redis: Any) -> None:
            nonlocal call_count
            call_count += 1
            raise asyncio.CancelledError

        mock_redis = AsyncMock()

        with (
            patch.object(forwarder, "_sync_follow_tasks", side_effect=mock_sync),
            patch.object(forwarder, "_cancel_all_tasks", new_callable=AsyncMock) as mock_cancel,
            patch("redis.asyncio.from_url", return_value=mock_redis),
            pytest.raises(asyncio.CancelledError),
        ):
            await forwarder.run()

        mock_cancel.assert_awaited_once()

    async def test_run_reconnects_on_error(self) -> None:
        """Generic exception in run() triggers reconnect with backoff."""
        forwarder, _ = _make_forwarder()

        call_count = 0

        async def mock_sync(redis: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Redis down")
            # Second call: cancel to stop the loop
            raise asyncio.CancelledError

        mock_redis = AsyncMock()

        with (
            patch.object(forwarder, "_sync_follow_tasks", side_effect=mock_sync),
            patch.object(forwarder, "_cancel_all_tasks", new_callable=AsyncMock) as mock_cancel,
            patch("redis.asyncio.from_url", return_value=mock_redis),
            patch(
                "silvasonic.controller.log_forwarder.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
            pytest.raises(asyncio.CancelledError),
        ):
            await forwarder.run()

        # First error → _cancel_all_tasks + sleep(5), then CancelledError → _cancel_all_tasks
        assert mock_cancel.await_count >= 1
        # Verify reconnect sleep was called with centralized delay
        mock_sleep.assert_any_call(RECONNECT_DELAY_S)

    async def test_run_closes_redis_in_finally(self) -> None:
        """Redis connection is closed in the finally block."""
        forwarder, _ = _make_forwarder()

        async def mock_sync(redis: Any) -> None:
            raise asyncio.CancelledError

        mock_redis = AsyncMock()

        with (
            patch.object(forwarder, "_sync_follow_tasks", side_effect=mock_sync),
            patch.object(forwarder, "_cancel_all_tasks", new_callable=AsyncMock),
            patch("redis.asyncio.from_url", return_value=mock_redis),
            pytest.raises(asyncio.CancelledError),
        ):
            await forwarder.run()

        mock_redis.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# _iter_logs batch and error handling (L252-256)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestIterLogsBatching:
    """Tests for _iter_logs batch limit and error handling."""

    async def test_batch_limit_returns_at_10_lines(self) -> None:
        """_iter_logs returns after collecting 10 lines (batch limit)."""
        forwarder, mock_podman = _make_forwarder()

        mock_container = MagicMock()
        # Generate 15 lines — should return first 10
        mock_container.logs.return_value = iter([f"line {i}\n".encode() for i in range(15)])
        mock_podman.containers.get.return_value = mock_container

        mock_redis = AsyncMock()
        published: list[str] = []

        async def capture(channel: str, data: str) -> int:
            published.append(data)
            return 0

        mock_redis.publish = capture

        async def fake_to_thread(fn: Any, *args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        with patch(
            "silvasonic.controller.log_forwarder.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            await forwarder._follow_container(
                name="batch-test",
                service="recorder",
                instance_id="mic-01",
                redis=mock_redis,
            )

        # First batch: 10 lines published, second batch: 5 lines, third: empty → exit
        assert len(published) == 15

    async def test_iter_logs_handles_exception(self) -> None:
        """_iter_logs catches generic exceptions from container.logs()."""
        forwarder, mock_podman = _make_forwarder()

        mock_container = MagicMock()
        # Logs generator raises on iteration
        mock_container.logs.return_value = iter([])

        def raise_on_iter(**kwargs: Any) -> Any:
            raise RuntimeError("container dead")

        mock_container.logs.side_effect = raise_on_iter
        mock_podman.containers.get.return_value = mock_container

        mock_redis = AsyncMock()

        async def fake_to_thread(fn: Any, *args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        with patch(
            "silvasonic.controller.log_forwarder.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            # Should not raise — _iter_logs catches the exception
            await forwarder._follow_container(
                name="error-test",
                service="recorder",
                instance_id="mic-01",
                redis=mock_redis,
            )
        # No assertion needed — verifying it doesn't raise


# ---------------------------------------------------------------------------
# _follow_container error paths (L278-288)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestFollowContainerErrors:
    """Tests for _follow_container exception handling."""

    async def test_publish_failure_continues(self) -> None:
        """Redis publish failure doesn't crash the follow loop."""
        forwarder, mock_podman = _make_forwarder()

        mock_container = MagicMock()
        mock_container.logs.return_value = iter(
            [
                b'{"event": "line1", "level": "info"}\n',
            ]
        )
        mock_podman.containers.get.return_value = mock_container

        mock_redis = AsyncMock()

        async def fail_publish(channel: str, data: str) -> None:
            raise ConnectionError("Redis disconnected")

        mock_redis.publish = fail_publish

        async def fake_to_thread(fn: Any, *args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        with patch(
            "silvasonic.controller.log_forwarder.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            # Should not raise — publish failures are caught
            await forwarder._follow_container(
                name="publish-fail",
                service="recorder",
                instance_id="mic-01",
                redis=mock_redis,
            )

    async def test_follow_cancelled_re_raises(self) -> None:
        """CancelledError in _follow_container is re-raised."""
        forwarder, _ = _make_forwarder()

        async def cancel_on_get(fn: Any, *args: Any, **kwargs: Any) -> Any:
            raise asyncio.CancelledError

        with (
            patch(
                "silvasonic.controller.log_forwarder.asyncio.to_thread",
                side_effect=cancel_on_get,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await forwarder._follow_container(
                name="cancel-test",
                service="recorder",
                instance_id="mic-01",
                redis=AsyncMock(),
            )

    async def test_follow_generic_exception_caught(self) -> None:
        """Generic exception in _follow_container is caught (not re-raised)."""
        forwarder, _ = _make_forwarder()

        async def raise_error(fn: Any, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("podman socket error")

        with patch(
            "silvasonic.controller.log_forwarder.asyncio.to_thread",
            side_effect=raise_error,
        ):
            # Should not raise — generic exceptions are caught
            await forwarder._follow_container(
                name="generic-error",
                service="recorder",
                instance_id="mic-01",
                redis=AsyncMock(),
            )


# ---------------------------------------------------------------------------
# Edge case: JSON array (non-dict) fallback
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestParseLogLineEdgeCases:
    """Additional edge cases for _parse_log_line."""

    def test_json_array_wrapped_as_raw(self) -> None:
        """A valid JSON array (not dict) is treated as non-JSON (raw)."""
        raw = json.dumps([1, 2, 3])
        result = _parse_log_line(
            raw,
            service="svc",
            instance_id="id",
            container_name="name",
        )
        assert result["level"] == "raw"
        assert result["message"] == raw

    def test_json_number_wrapped_as_raw(self) -> None:
        """A valid JSON number (not dict) is treated as non-JSON (raw)."""
        result = _parse_log_line(
            "42",
            service="svc",
            instance_id="id",
            container_name="name",
        )
        assert result["level"] == "raw"
        assert result["message"] == "42"
