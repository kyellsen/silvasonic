"""Unit tests for ControllerService.

Covers the ControllerService (SilvaService subclass) including:
- Background health monitors (_monitor_database, _monitor_podman)
- get_extra_meta() providing host_resources
- load_config() DB seeding hook
- run() lifecycle with shutdown event
- run() lifecycle with shutdown event
- _emit_status_summary
- DB/Podman state-change logging

Settings-contract tests (defaults, env overrides) live in test_settings.py.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.health import HealthMonitor


def _make_bare_service() -> Any:
    """Create a bare ControllerService without triggering SilvaService.__init__.

    Sets up a mock _ctx with a real HealthMonitor so the `svc.health` property
    works without mypy complaints.

    Returns ``Any`` so mock attributes (return_value, assert_called, etc.)
    are accessible without mypy ``attr-defined`` errors.
    """
    from silvasonic.controller.__main__ import ControllerService
    from silvasonic.controller.settings import ControllerSettings

    svc = ControllerService.__new__(ControllerService)
    svc._ctx = MagicMock()
    svc._ctx.health = HealthMonitor()
    svc._podman_client = MagicMock()
    svc._container_manager = MagicMock()
    svc._reconciliation_loop = MagicMock()
    svc._nudge_subscriber = MagicMock()
    # Phase 4: USB detection components
    svc._device_scanner = MagicMock()
    svc._profile_matcher = MagicMock()
    # Phase 5: Log forwarding
    svc._log_forwarder = MagicMock()
    # Stats and state tracking (added for production logging)
    svc._cfg = ControllerSettings()
    svc._stats = None
    svc._db_was_connected = None
    svc._podman_was_connected = None
    return svc


# ---------------------------------------------------------------------------
# _monitor_database
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMonitorDatabase:
    """Tests for the _monitor_database coroutine."""

    async def test_monitor_database_connected(self) -> None:
        """Updates HealthMonitor with 'Connected' when DB is reachable."""
        svc = _make_bare_service()

        with (
            patch(
                "silvasonic.controller.__main__.check_database_connection",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_database()

        status = svc.health.get_status()
        assert status["components"]["database"]["healthy"] is True
        assert status["components"]["database"]["details"] == "Connected"

    async def test_monitor_database_failed(self) -> None:
        """Updates HealthMonitor with 'Connection failed' when DB is down."""
        svc = _make_bare_service()

        with (
            patch(
                "silvasonic.controller.__main__.check_database_connection",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_database()

        status = svc.health.get_status()
        assert status["components"]["database"]["healthy"] is False
        assert status["components"]["database"]["details"] == "Connection failed"


# ---------------------------------------------------------------------------
# _monitor_podman
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMonitorPodman:
    """Tests for the _monitor_podman coroutine."""

    async def test_monitor_podman_connected(self) -> None:
        """Reports healthy when Podman socket is reachable."""
        svc = _make_bare_service()
        svc._podman_client.socket_path = "/run/podman/podman.sock"
        svc._podman_client.ping.return_value = True
        svc._podman_client.list_managed_containers.return_value = [
            {"id": "abc", "name": "rec1", "status": "running", "labels": {}}
        ]
        svc._podman_client.connect.return_value = None

        call_count = 0

        async def mock_sleep(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread,
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                side_effect=mock_sleep,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            mock_to_thread.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
            await svc._monitor_podman()

        status = svc.health.get_status()
        assert status["components"]["podman"]["healthy"] is True
        assert status["components"]["podman"]["details"] == "Connected"
        assert "containers" in status["components"]
        assert status["components"]["containers"]["details"] == "1 managed containers"

    async def test_monitor_podman_disconnected(self) -> None:
        """Reports unhealthy when Podman socket is unreachable."""
        svc = _make_bare_service()
        svc._podman_client.socket_path = "/run/podman/podman.sock"
        svc._podman_client.ping.return_value = False
        svc._podman_client.connect.return_value = None

        call_count = 0

        async def mock_sleep(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread,
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                side_effect=mock_sleep,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            mock_to_thread.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
            await svc._monitor_podman()

        status = svc.health.get_status()
        assert status["components"]["podman"]["healthy"] is False
        assert status["components"]["podman"]["details"] == "Socket unreachable"

    async def test_monitor_podman_connect_failure(self) -> None:
        """Reports unhealthy when initial connect() raises."""
        from silvasonic.controller.podman_client import PodmanConnectionError

        svc = _make_bare_service()
        svc._podman_client.socket_path = "/run/podman/podman.sock"
        svc._podman_client.connect.side_effect = PodmanConnectionError("no socket")
        svc._podman_client.ping.return_value = False

        call_count = 0

        async def mock_sleep(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread,
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                side_effect=mock_sleep,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            mock_to_thread.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
            await svc._monitor_podman()

        status = svc.health.get_status()
        assert status["components"]["podman"]["healthy"] is False

    async def test_monitor_podman_socket_not_found(self) -> None:
        """Registers podman as optional when socket path does not exist."""
        svc = _make_bare_service()
        svc._podman_client.socket_path = "/nonexistent/podman.sock"

        with patch("pathlib.Path.exists", return_value=False):
            await svc._monitor_podman()

        status = svc.health.get_status()
        assert status["components"]["podman"]["healthy"] is False
        assert status["components"]["podman"]["required"] is False
        # Overall status should be ok because podman is optional
        assert status["status"] == "ok"


# ---------------------------------------------------------------------------
# get_extra_meta
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGetExtraMeta:
    """Tests for the get_extra_meta() override."""

    def test_returns_host_resources(self) -> None:
        """get_extra_meta() includes host_resources."""
        svc = _make_bare_service()
        mock_hrc = MagicMock()
        mock_hrc.collect.return_value = {"cpu_percent": 23.5, "cpu_count": 4}
        svc._host_resources = mock_hrc

        meta = svc.get_extra_meta()

        assert "host_resources" in meta
        assert meta["host_resources"]["cpu_percent"] == 23.5
        assert meta["host_resources"]["cpu_count"] == 4
        mock_hrc.collect.assert_called_once()


# ---------------------------------------------------------------------------
# ControllerService.load_config()
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestControllerLoadConfig:
    """Tests for the load_config() hook (DB seeding)."""

    async def test_load_config_calls_seeders(self) -> None:
        """load_config() runs all seeders and calls scan_and_sync_devices."""
        svc = _make_bare_service()
        svc._reconciliation_loop.scan_and_sync_devices = AsyncMock(return_value=0)

        with (
            patch(
                "silvasonic.controller.__main__.get_session",
            ) as mock_session,
            patch(
                "silvasonic.controller.__main__.run_all_seeders",
                new_callable=AsyncMock,
            ) as mock_seeders,
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()

            await svc.load_config()

        mock_seeders.assert_awaited_once_with(mock_ctx)
        svc._reconciliation_loop.scan_and_sync_devices.assert_awaited_once()


# ---------------------------------------------------------------------------
# ControllerService.run()
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestControllerServiceRun:
    """Tests for the run() coroutine."""

    async def test_run_starts_monitors_and_exits_on_shutdown(self) -> None:
        """run() starts background tasks and exits when shutdown_event is set."""
        svc = _make_bare_service()
        svc._shutdown_event = asyncio.Event()

        # Mock the monitor methods to be slow no-ops so they don't finish before cancellation
        async def noop_forever() -> None:
            await asyncio.Event().wait()

        svc._reconciliation_loop.run = MagicMock(side_effect=noop_forever)
        svc._nudge_subscriber.run = MagicMock(side_effect=noop_forever)
        svc._log_forwarder.run = MagicMock(side_effect=noop_forever)

        # Trigger shutdown immediately before starting the loop to prevent hanging
        svc._shutdown_event.set()

        with (
            patch.object(svc, "_monitor_database", side_effect=noop_forever),
            patch.object(svc, "_monitor_podman", side_effect=noop_forever),
        ):
            await svc.run()

        # Health should have been initialized (it happens before the loop)
        status = svc.health.get_status()
        assert "controller" in status["components"]

        # Verify clean shutdown procedures are executed
        svc._podman_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# _emit_status_summary
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestEmitStatusSummary:
    """Tests for the _emit_status_summary method."""

    async def test_summary_logs_container_names(self) -> None:
        """_emit_status_summary logs container names and stats."""
        svc = _make_bare_service()
        svc._container_manager.list_managed.return_value = [
            {"name": "silvasonic-recorder-mic1", "status": "running"},
            {"name": "silvasonic-recorder-mic2", "status": "running"},
        ]

        summary = {
            "interval_s": 300.0,
            "interval_reconcile_cycles": 300,
            "total_reconcile_cycles": 600,
            "uptime_s": 600,
        }

        with (
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
            patch("silvasonic.controller.__main__.log") as mock_log,
        ):
            await svc._emit_status_summary(summary)

        # Summary log should have been emitted
        info_calls = [c for c in mock_log.info.call_args_list if c[0][0] == "controller.summary"]
        assert len(info_calls) == 1
        call_kwargs = info_calls[0].kwargs
        assert call_kwargs["containers_running"] == 2
        assert "silvasonic-recorder-mic1" in call_kwargs["container_names"]
        assert call_kwargs["interval_reconcile_cycles"] == 300

    async def test_summary_handles_podman_error(self) -> None:
        """_emit_status_summary handles list_managed failure gracefully."""
        svc = _make_bare_service()
        svc._container_manager.list_managed.side_effect = RuntimeError("Podman crashed")

        with (
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
            patch("silvasonic.controller.__main__.log") as mock_log,
        ):
            await svc._emit_status_summary({"uptime_s": 10})

        info_calls = [c for c in mock_log.info.call_args_list if c[0][0] == "controller.summary"]
        assert len(info_calls) == 1
        assert info_calls[0].kwargs["containers_running"] == 0
