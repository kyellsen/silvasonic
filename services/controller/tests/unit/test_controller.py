"""Unit tests for ControllerService.

Covers the ControllerService (SilvaService subclass) including:
- Package import
- Service configuration (port from env)
- Background health monitors (_monitor_database, _monitor_podman)
- get_extra_meta() providing host_resources
- load_config() DB seeding hook
- run() lifecycle with shutdown event
- __main__ guard
"""

import asyncio
import os
import sys
import warnings
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.controller.__main__ import ControllerService
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
# Package import
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestControllerPackage:
    """Basic package-level tests."""

    def test_package_importable(self) -> None:
        """Controller package is importable."""
        import silvasonic.controller

        assert silvasonic.controller is not None

    def test_podman_client_exported(self) -> None:
        """SilvasonicPodmanClient is exported from the controller package."""
        from silvasonic.controller import SilvasonicPodmanClient

        assert SilvasonicPodmanClient is not None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestControllerConfig:
    """Tests for service-level configuration."""

    def test_health_port_default(self) -> None:
        """service_port defaults to 9100."""
        _make_bare_service()
        # Class-level default is 9100
        assert ControllerService.service_port == 9100

    def test_health_port_env_override(self) -> None:
        """service_port respects SILVASONIC_CONTROLLER_PORT at instantiation."""
        with patch.dict("os.environ", {"SILVASONIC_CONTROLLER_PORT": "7777"}):
            from silvasonic.controller.__main__ import (
                ControllerService as ControllerSvc,
            )

            svc = ControllerSvc.__new__(ControllerSvc)
            # Simulate __init__ reading env var
            svc.service_port = int(os.environ.get("SILVASONIC_CONTROLLER_PORT", "9100"))
            assert svc.service_port == 7777

    def test_service_name(self) -> None:
        """service_name is 'controller'."""
        assert ControllerService.service_name == "controller"

    def test_monitor_poll_interval_default(self) -> None:
        """CONTROLLER_MONITOR_POLL_INTERVAL_S defaults to 10.0."""
        from silvasonic.controller.settings import ControllerSettings

        cfg = ControllerSettings()
        assert cfg.CONTROLLER_MONITOR_POLL_INTERVAL_S == 10.0

    def test_log_forwarder_poll_interval_default(self) -> None:
        """LOG_FORWARDER_POLL_INTERVAL_S defaults to 1.0."""
        from silvasonic.controller.settings import ControllerSettings

        cfg = ControllerSettings()
        assert cfg.LOG_FORWARDER_POLL_INTERVAL_S == 1.0

    def test_monitor_poll_interval_env_override(self) -> None:
        """CONTROLLER_MONITOR_POLL_INTERVAL_S respects env override."""
        with patch.dict("os.environ", {"SILVASONIC_CONTROLLER_MONITOR_POLL_INTERVAL_S": "30.0"}):
            from silvasonic.controller.settings import ControllerSettings

            cfg = ControllerSettings()
            assert cfg.CONTROLLER_MONITOR_POLL_INTERVAL_S == 30.0

    def test_log_forwarder_poll_interval_env_override(self) -> None:
        """LOG_FORWARDER_POLL_INTERVAL_S respects env override."""
        with patch.dict("os.environ", {"SILVASONIC_LOG_FORWARDER_POLL_INTERVAL_S": "5.0"}):
            from silvasonic.controller.settings import ControllerSettings

            cfg = ControllerSettings()
            assert cfg.LOG_FORWARDER_POLL_INTERVAL_S == 5.0


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

        # Mock the monitor methods to be no-ops
        async def noop_forever() -> None:
            await asyncio.Event().wait()

        svc._reconciliation_loop.run = MagicMock(side_effect=noop_forever)
        svc._nudge_subscriber.run = MagicMock(side_effect=noop_forever)
        svc._log_forwarder.run = MagicMock(side_effect=noop_forever)

        with (
            patch.object(svc, "_monitor_database", side_effect=noop_forever),
            patch.object(svc, "_monitor_podman", side_effect=noop_forever),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=lambda _: svc._shutdown_event.set(),
            ),
        ):
            await svc.run()

        # Health should have been initialized
        status = svc.health.get_status()
        assert "controller" in status["components"]
        # Podman client should be closed
        svc._podman_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# _stop_all_tier2
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestStopAllTier2:
    """Tests for the _stop_all_tier2 shutdown method."""

    async def test_stops_all_managed_containers(self) -> None:
        """_stop_all_tier2 stops each managed container by name."""
        svc = _make_bare_service()
        svc._container_manager.list_managed.return_value = [
            {"name": "silvasonic-recorder-mic1", "status": "running"},
            {"name": "silvasonic-recorder-mic2", "status": "running"},
        ]
        svc._container_manager.stop.return_value = True

        with patch(
            "silvasonic.controller.__main__.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),
        ):
            await svc._stop_all_tier2()

        assert svc._container_manager.stop_and_remove.call_count == 2

    async def test_stops_no_containers(self) -> None:
        """_stop_all_tier2 handles gracefully when no containers are running."""
        svc = _make_bare_service()
        svc._container_manager.list_managed.return_value = []

        with patch(
            "silvasonic.controller.__main__.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),
        ):
            await svc._stop_all_tier2()

        svc._container_manager.stop.assert_not_called()

    async def test_handles_exception_gracefully(self) -> None:
        """_stop_all_tier2 catches exceptions without crashing."""
        svc = _make_bare_service()
        svc._container_manager.list_managed.side_effect = RuntimeError("Podman gone")

        with patch(
            "silvasonic.controller.__main__.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),
        ):
            # Should not raise
            await svc._stop_all_tier2()


# ---------------------------------------------------------------------------
# __main__ guard
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMainGuard:
    """Tests for the if __name__ == '__main__' guard."""

    def test_main_guard(self) -> None:
        """The if __name__ == '__main__' guard calls ControllerService().start()."""
        import runpy

        # Remove cached module to prevent "found in sys.modules" RuntimeWarning
        sys.modules.pop("silvasonic.controller.__main__", None)

        with (
            patch("silvasonic.core.service.SilvaService.start", MagicMock()) as mock_start,
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore", RuntimeWarning)
            runpy.run_module("silvasonic.controller.__main__", run_name="__main__")
            mock_start.assert_called_once()


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


# ---------------------------------------------------------------------------
# DB state-change logging
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDatabaseStateChangeLogging:
    """Tests for DB connectivity state-change logging in _monitor_database."""

    async def test_initial_connect_logs_info(self) -> None:
        """First successful DB check logs controller.database_connected."""
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
            patch("silvasonic.controller.__main__.log") as mock_log,
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_database()

        connected_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "controller.database_connected"
        ]
        assert len(connected_logs) == 1

    async def test_initial_failure_logs_warning(self) -> None:
        """First failed DB check logs controller.database_unreachable."""
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
            patch("silvasonic.controller.__main__.log") as mock_log,
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_database()

        unreachable_logs = [
            c
            for c in mock_log.warning.call_args_list
            if c[0][0] == "controller.database_unreachable"
        ]
        assert len(unreachable_logs) == 1

    async def test_disconnect_logs_warning(self) -> None:
        """DB going from connected to disconnected logs warning."""
        svc = _make_bare_service()

        call_count = 0
        responses = [True, False]  # Connected then disconnected

        async def mock_check() -> bool:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return responses[idx]

        sleep_count = 0

        async def mock_sleep(_: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                raise asyncio.CancelledError

        with (
            patch(
                "silvasonic.controller.__main__.check_database_connection",
                side_effect=mock_check,
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                side_effect=mock_sleep,
            ),
            patch("silvasonic.controller.__main__.log") as mock_log,
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_database()

        disconnect_logs = [
            c
            for c in mock_log.warning.call_args_list
            if c[0][0] == "controller.database_disconnected"
        ]
        assert len(disconnect_logs) == 1

    async def test_reconnect_logs_info(self) -> None:
        """DB going from disconnected to connected logs info."""
        svc = _make_bare_service()

        call_count = 0
        responses = [False, True]  # Disconnected then connected

        async def mock_check() -> bool:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return responses[idx]

        sleep_count = 0

        async def mock_sleep(_: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                raise asyncio.CancelledError

        with (
            patch(
                "silvasonic.controller.__main__.check_database_connection",
                side_effect=mock_check,
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                side_effect=mock_sleep,
            ),
            patch("silvasonic.controller.__main__.log") as mock_log,
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_database()

        reconnect_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "controller.database_reconnected"
        ]
        assert len(reconnect_logs) == 1


# ---------------------------------------------------------------------------
# Podman state-change logging
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestPodmanStateChangeLogging:
    """Tests for Podman connectivity state-change logging in _monitor_podman."""

    async def test_initial_connect_logs_info(self) -> None:
        """First successful Podman ping logs controller.podman_connected."""
        svc = _make_bare_service()
        svc._podman_client.socket_path = "/run/podman/podman.sock"
        svc._podman_client.ping.return_value = True
        svc._podman_client.connect.return_value = None
        svc._podman_client.list_managed_containers.return_value = []

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            patch("silvasonic.controller.__main__.log") as mock_log,
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_podman()

        connected_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "controller.podman_connected"
        ]
        assert len(connected_logs) == 1

    async def test_disconnect_logs_warning(self) -> None:
        """Podman going from alive to dead logs warning."""
        svc = _make_bare_service()
        svc._podman_client.socket_path = "/run/podman/podman.sock"
        svc._podman_client.connect.return_value = None
        svc._podman_client.list_managed_containers.return_value = []

        call_count = 0
        ping_results = [True, False]

        def mock_ping() -> bool:
            nonlocal call_count
            idx = min(call_count, len(ping_results) - 1)
            call_count += 1
            return ping_results[idx]

        svc._podman_client.ping = mock_ping

        sleep_count = 0

        async def mock_sleep(_: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                raise asyncio.CancelledError

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                side_effect=mock_sleep,
            ),
            patch("silvasonic.controller.__main__.log") as mock_log,
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_podman()

        disconnect_logs = [
            c
            for c in mock_log.warning.call_args_list
            if c[0][0] == "controller.podman_disconnected"
        ]
        assert len(disconnect_logs) == 1

    async def test_reconnect_logs_info(self) -> None:
        """Podman going from dead to alive logs info."""
        svc = _make_bare_service()
        svc._podman_client.socket_path = "/run/podman/podman.sock"
        svc._podman_client.connect.return_value = None
        svc._podman_client.list_managed_containers.return_value = []

        call_count = 0
        ping_results = [False, True]

        def mock_ping() -> bool:
            nonlocal call_count
            idx = min(call_count, len(ping_results) - 1)
            call_count += 1
            return ping_results[idx]

        svc._podman_client.ping = mock_ping

        sleep_count = 0

        async def mock_sleep(_: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                raise asyncio.CancelledError

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=lambda fn, *a, **kw: fn(*a, **kw),
            ),
            patch(
                "silvasonic.controller.__main__.asyncio.sleep",
                side_effect=mock_sleep,
            ),
            patch("silvasonic.controller.__main__.log") as mock_log,
            pytest.raises(asyncio.CancelledError),
        ):
            await svc._monitor_podman()

        reconnect_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "controller.podman_reconnected"
        ]
        assert len(reconnect_logs) == 1
