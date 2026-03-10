"""Unit tests for silvasonic-controller service — 100 % coverage.

Tests the ControllerService (SilvaService subclass) including:
- Package import
- Service configuration (port from env)
- Background health monitors (_monitor_database, _monitor_podman)
- get_extra_meta() providing host_resources
- run() lifecycle with shutdown event
- __main__ guard

Tests for SilvasonicPodmanClient:
- connect() with retry logic
- ping() success/failure
- list_containers() / list_managed_containers()
- close()
"""

import asyncio
import importlib
import os
import sys
import warnings
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

    svc = ControllerService.__new__(ControllerService)
    svc._ctx = MagicMock()
    svc._ctx.health = HealthMonitor()
    svc._podman_client = MagicMock()
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
        os.environ.pop("SILVASONIC_CONTROLLER_PORT", None)
        mod = importlib.import_module("silvasonic.controller.__main__")
        importlib.reload(mod)
        assert mod.ControllerService.service_port == 9100

    def test_health_port_env_override(self) -> None:
        """service_port respects the SILVASONIC_CONTROLLER_PORT env var."""
        with patch.dict("os.environ", {"SILVASONIC_CONTROLLER_PORT": "7777"}):
            mod = importlib.import_module("silvasonic.controller.__main__")
            importlib.reload(mod)
            assert mod.ControllerService.service_port == 7777

    def test_service_name(self) -> None:
        """service_name is 'controller'."""
        from silvasonic.controller.__main__ import ControllerService

        assert ControllerService.service_name == "controller"


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
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread,
            patch("silvasonic.controller.__main__.asyncio.sleep", side_effect=mock_sleep),
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
        svc._podman_client.ping.return_value = False
        svc._podman_client.connect.return_value = None

        call_count = 0

        async def mock_sleep(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError

        with (
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread,
            patch("silvasonic.controller.__main__.asyncio.sleep", side_effect=mock_sleep),
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
        svc._podman_client.connect.side_effect = PodmanConnectionError("no socket")
        svc._podman_client.ping.return_value = False

        call_count = 0

        async def mock_sleep(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError

        with (
            patch(
                "silvasonic.controller.__main__.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread,
            patch("silvasonic.controller.__main__.asyncio.sleep", side_effect=mock_sleep),
            pytest.raises(asyncio.CancelledError),
        ):
            mock_to_thread.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
            await svc._monitor_podman()

        status = svc.health.get_status()
        assert status["components"]["podman"]["healthy"] is False


# ---------------------------------------------------------------------------
# get_extra_meta
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGetExtraMeta:
    """Tests for the get_extra_meta() override."""

    def test_returns_host_resources(self) -> None:
        """get_extra_meta() includes host_resources from HostResourceCollector."""
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
        async def noop_db() -> None:
            await asyncio.Event().wait()

        async def noop_podman() -> None:
            await asyncio.Event().wait()

        with (
            patch.object(svc, "_monitor_database", side_effect=noop_db),
            patch.object(svc, "_monitor_podman", side_effect=noop_podman),
        ):
            # Set shutdown after a short delay
            async def trigger_shutdown() -> None:
                await asyncio.sleep(0.05)
                svc._shutdown_event.set()

            shutdown_task = asyncio.create_task(trigger_shutdown())
            await svc.run()
            await shutdown_task

        # Health should have been initialized
        status = svc.health.get_status()
        assert "controller" in status["components"]
        # Podman client should be closed
        svc._podman_client.close.assert_called_once()


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


# ===========================================================================
# SilvasonicPodmanClient unit tests
# ===========================================================================


@pytest.mark.unit
class TestSilvasonicPodmanClientInit:
    """Tests for SilvasonicPodmanClient initialization."""

    def test_default_socket_path(self) -> None:
        """Uses CONTAINER_SOCKET env var or default path."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CONTAINER_SOCKET", None)
            client = SilvasonicPodmanClient()
            assert client.socket_url == "unix:///var/run/container.sock"
            assert not client.is_connected

    def test_custom_socket_path(self) -> None:
        """Respects explicitly passed socket_path."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient(socket_path="/custom/socket.sock")
        assert client.socket_url == "unix:///custom/socket.sock"

    def test_env_var_socket_path(self) -> None:
        """Reads CONTAINER_SOCKET from env."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        with patch.dict(os.environ, {"CONTAINER_SOCKET": "/env/podman.sock"}):
            client = SilvasonicPodmanClient()
            assert client.socket_url == "unix:///env/podman.sock"


@pytest.mark.unit
class TestSilvasonicPodmanClientConnect:
    """Tests for SilvasonicPodmanClient.connect() with retry logic."""

    def test_connect_success_first_attempt(self) -> None:
        """Connects successfully on first attempt."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        mock_podman_class = MagicMock()
        mock_instance = MagicMock()
        mock_instance.ping.return_value = True
        mock_podman_class.return_value = mock_instance

        client = SilvasonicPodmanClient(socket_path="/test.sock")
        with patch("podman.PodmanClient", mock_podman_class):
            client.connect()

        assert client.is_connected
        mock_podman_class.assert_called_once_with(base_url="unix:///test.sock")

    def test_connect_success_after_retries(self) -> None:
        """Connects after failing the first two attempts."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        mock_podman_class = MagicMock()
        mock_instance = MagicMock()
        # Fail twice, succeed on third
        mock_instance.ping.side_effect = [ConnectionError, ConnectionError, True]
        mock_podman_class.return_value = mock_instance

        client = SilvasonicPodmanClient(socket_path="/test.sock", max_retries=3, retry_delay=0.01)
        with patch("podman.PodmanClient", mock_podman_class):
            client.connect()

        assert client.is_connected

    def test_connect_exhausted_retries(self) -> None:
        """Raises PodmanConnectionError after exhausting retries."""
        from silvasonic.controller.podman_client import (
            PodmanConnectionError,
            SilvasonicPodmanClient,
        )

        mock_podman_class = MagicMock()
        mock_instance = MagicMock()
        mock_instance.ping.side_effect = ConnectionError("fail")
        mock_podman_class.return_value = mock_instance

        client = SilvasonicPodmanClient(socket_path="/test.sock", max_retries=2, retry_delay=0.01)
        with (
            patch("podman.PodmanClient", mock_podman_class),
            pytest.raises(PodmanConnectionError, match="Failed to connect"),
        ):
            client.connect()

        assert not client.is_connected

    def test_connect_ping_returns_false(self) -> None:
        """Raises PodmanConnectionError when ping consistently returns False."""
        from silvasonic.controller.podman_client import (
            PodmanConnectionError,
            SilvasonicPodmanClient,
        )

        mock_podman_class = MagicMock()
        mock_instance = MagicMock()
        mock_instance.ping.return_value = False
        mock_podman_class.return_value = mock_instance

        client = SilvasonicPodmanClient(socket_path="/test.sock", max_retries=2, retry_delay=0.01)
        with (
            patch("podman.PodmanClient", mock_podman_class),
            pytest.raises(PodmanConnectionError),
        ):
            client.connect()


@pytest.mark.unit
class TestSilvasonicPodmanClientPing:
    """Tests for SilvasonicPodmanClient.ping()."""

    def test_ping_success(self) -> None:
        """Returns True when engine responds."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.ping.return_value = True
        client._connected = True

        assert client.ping() is True
        assert client.is_connected

    def test_ping_failure(self) -> None:
        """Returns False and sets disconnected when engine fails."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.ping.side_effect = ConnectionError("lost")
        client._connected = True

        assert client.ping() is False
        assert not client.is_connected

    def test_ping_no_client(self) -> None:
        """Returns False when client is None."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = None
        client._connected = False

        assert client.ping() is False


@pytest.mark.unit
class TestSilvasonicPodmanClientListContainers:
    """Tests for list_containers() and list_managed_containers()."""

    def test_list_containers_returns_info(self) -> None:
        """Returns list of container dicts."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_container.name = "silvasonic-recorder-mic1"
        mock_container.status = "running"
        mock_container.labels = {"io.silvasonic.owner": "controller"}

        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.containers.list.return_value = [mock_container]
        client._connected = True

        result = client.list_containers()
        assert len(result) == 1
        assert result[0]["name"] == "silvasonic-recorder-mic1"
        assert result[0]["status"] == "running"

    def test_list_containers_no_client(self) -> None:
        """Returns empty list when not connected."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = None

        assert client.list_containers() == []

    def test_list_containers_error(self) -> None:
        """Returns empty list on error."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.containers.list.side_effect = RuntimeError("boom")
        client._connected = True

        assert client.list_containers() == []

    def test_list_managed_containers(self) -> None:
        """Filters by io.silvasonic.owner=controller label."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.containers.list.return_value = []
        client._connected = True

        client.list_managed_containers()
        client._client.containers.list.assert_called_once_with(
            filters={"label": ["io.silvasonic.owner=controller"]}
        )


@pytest.mark.unit
class TestSilvasonicPodmanClientClose:
    """Tests for close()."""

    def test_close_connected(self) -> None:
        """Calls client.close() and cleans up state."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        mock_inner = MagicMock()
        client._client = mock_inner
        client._connected = True

        client.close()

        mock_inner.close.assert_called_once()
        assert client._client is None
        assert not client.is_connected

    def test_close_already_disconnected(self) -> None:
        """No-op when already disconnected."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = None
        client._connected = False

        client.close()  # Should not raise

    def test_close_handles_error(self) -> None:
        """Cleans up even when close() raises."""
        from silvasonic.controller.podman_client import SilvasonicPodmanClient

        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        mock_inner = MagicMock()
        mock_inner.close.side_effect = RuntimeError("cleanup failed")
        client._client = mock_inner
        client._connected = True

        client.close()

        assert client._client is None
        assert not client.is_connected
