"""Unit tests for SilvasonicPodmanClient.

Covers initialization, connect() with retry logic, ping(), list_containers(),
list_managed_containers(), close(), container_info(), and the containers
property.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from silvasonic.controller.podman_client import SilvasonicPodmanClient, container_info

# ===================================================================
# Initialization
# ===================================================================


@pytest.mark.unit
class TestSilvasonicPodmanClientInit:
    """Tests for SilvasonicPodmanClient initialization."""

    def test_default_socket_path(self) -> None:
        """Uses SILVASONIC_CONTAINER_SOCKET env var or default path."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SILVASONIC_CONTAINER_SOCKET", None)
            client = SilvasonicPodmanClient()
            assert client.socket_url == "unix:///var/run/container.sock"
            assert not client.is_connected

    def test_custom_socket_path(self) -> None:
        """Respects explicitly passed socket_path."""
        client = SilvasonicPodmanClient(socket_path="/custom/socket.sock")
        assert client.socket_url == "unix:///custom/socket.sock"

    def test_env_var_socket_path(self) -> None:
        """Reads SILVASONIC_CONTAINER_SOCKET from env."""
        with patch.dict(os.environ, {"SILVASONIC_CONTAINER_SOCKET": "/env/podman.sock"}):
            client = SilvasonicPodmanClient()
            assert client.socket_url == "unix:///env/podman.sock"


# ===================================================================
# connect()
# ===================================================================


@pytest.mark.unit
class TestSilvasonicPodmanClientConnect:
    """Tests for SilvasonicPodmanClient.connect() with retry logic."""

    def test_connect_success_first_attempt(self) -> None:
        """Connects successfully on first attempt."""
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
        mock_podman_class = MagicMock()
        mock_instance = MagicMock()
        # Fail twice, succeed on third
        mock_instance.ping.side_effect = [
            ConnectionError,
            ConnectionError,
            True,
        ]
        mock_podman_class.return_value = mock_instance

        client = SilvasonicPodmanClient(socket_path="/test.sock", max_retries=3, retry_delay=0.01)
        with patch("podman.PodmanClient", mock_podman_class):
            client.connect()

        assert client.is_connected

    def test_connect_exhausted_retries(self) -> None:
        """Raises PodmanConnectionError after exhausting retries."""
        from silvasonic.controller.podman_client import PodmanConnectionError

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
        from silvasonic.controller.podman_client import PodmanConnectionError

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

    def test_connect_unexpected_exception_retries(self) -> None:
        """connect() handles unexpected exceptions with retry + sleep."""
        from silvasonic.controller.podman_client import PodmanConnectionError

        mock_podman_class = MagicMock()
        mock_instance = MagicMock()
        mock_instance.ping.side_effect = TypeError("unexpected")
        mock_podman_class.return_value = mock_instance

        client = SilvasonicPodmanClient(socket_path="/test.sock", max_retries=2, retry_delay=0.01)
        with (
            patch("podman.PodmanClient", mock_podman_class),
            patch("time.sleep") as mock_sleep,
            patch("silvasonic.controller.podman_client.log"),
            pytest.raises(PodmanConnectionError),
        ):
            client.connect()

        # Should sleep between retries (only first attempt, not last)
        mock_sleep.assert_called_once_with(0.01)

    def test_connect_retry_log_level_demotion(self) -> None:
        """First attempt logs info, subsequent attempts log debug."""
        from silvasonic.controller.podman_client import PodmanConnectionError

        mock_podman_class = MagicMock()
        mock_instance = MagicMock()
        mock_instance.ping.return_value = False
        mock_podman_class.return_value = mock_instance

        client = SilvasonicPodmanClient(socket_path="/test.sock", max_retries=3, retry_delay=0.01)
        with (
            patch("podman.PodmanClient", mock_podman_class),
            patch("silvasonic.controller.podman_client.log") as mock_log,
            pytest.raises(PodmanConnectionError),
        ):
            client.connect()

        # First call should be info, subsequent should be debug
        info_calls = [c for c in mock_log.info.call_args_list if c[0][0] == "podman.connecting"]
        debug_calls = [c for c in mock_log.debug.call_args_list if c[0][0] == "podman.connecting"]
        assert len(info_calls) == 1, "Only first attempt should be info"
        assert len(debug_calls) == 2, "Attempts 2 and 3 should be debug"

    def test_connect_sleeps_between_expected_errors(self) -> None:
        """connect() sleeps between retries for ConnectionError/OSError."""
        from silvasonic.controller.podman_client import PodmanConnectionError

        mock_podman_class = MagicMock()
        mock_podman_class.side_effect = ConnectionError("refused")

        client = SilvasonicPodmanClient(socket_path="/test.sock", max_retries=3, retry_delay=0.01)
        with (
            patch("podman.PodmanClient", mock_podman_class),
            patch("time.sleep") as mock_sleep,
            pytest.raises(PodmanConnectionError),
        ):
            client.connect()

        # Should sleep between each retry (2 sleeps for 3 attempts)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(0.01)


# ===================================================================
# ping()
# ===================================================================


@pytest.mark.unit
class TestSilvasonicPodmanClientPing:
    """Tests for SilvasonicPodmanClient.ping()."""

    def test_ping_success(self) -> None:
        """Returns True when engine responds."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.ping.return_value = True
        client._connected = True

        assert client.ping() is True
        assert client.is_connected

    def test_ping_failure(self) -> None:
        """Returns False and sets disconnected when engine fails."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.ping.side_effect = ConnectionError("lost")
        client._connected = True

        assert client.ping() is False
        assert not client.is_connected

    def test_ping_no_client(self) -> None:
        """Returns False when client is None."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = None
        client._connected = False

        assert client.ping() is False

    def test_ping_unexpected_exception(self) -> None:
        """ping() returns False on unexpected exceptions."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.ping.side_effect = TypeError("unexpected")
        client._connected = True

        assert client.ping() is False
        assert not client.is_connected

    def test_ping_os_error(self) -> None:
        """ping() returns False on OSError (connection reset)."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.ping.side_effect = OSError("connection reset")
        client._connected = True

        assert client.ping() is False
        assert not client.is_connected


# ===================================================================
# container_info()
# ===================================================================


@pytest.mark.unit
class TestContainerInfo:
    """Tests for container_info() — sparse/full mode, name normalization."""

    def test_sparse_mode_state_string(self) -> None:
        """Sparse mode: attrs['State'] is a plain string (podman-py v5.7+)."""
        c = MagicMock()
        c.id = "abc123"
        c.name = "silvasonic-recorder-test"
        c.attrs = {"State": "running"}
        c.labels = {}

        info = container_info(c)
        assert info["status"] == "running"
        assert info["name"] == "silvasonic-recorder-test"

    def test_full_mode_state_dict(self) -> None:
        """Full mode: attrs['State'] is a dict with 'Status' key."""
        c = MagicMock()
        c.id = "abc123"
        c.name = "silvasonic-recorder-test"
        c.attrs = {"State": {"Status": "exited", "ExitCode": 0}}
        c.labels = {}

        info = container_info(c)
        assert info["status"] == "exited"

    def test_name_slash_prefix_stripped(self) -> None:
        """Podman API may prefix names with '/' — must be stripped."""
        c = MagicMock()
        c.id = "abc123"
        c.name = "/silvasonic-recorder-test"
        c.attrs = {"State": "running"}
        c.labels = {}

        info = container_info(c)
        assert info["name"] == "silvasonic-recorder-test"

    def test_name_without_slash_unchanged(self) -> None:
        """Names without '/' prefix pass through unchanged."""
        c = MagicMock()
        c.id = "abc123"
        c.name = "silvasonic-recorder-test"
        c.attrs = {"State": "running"}
        c.labels = {}

        info = container_info(c)
        assert info["name"] == "silvasonic-recorder-test"

    def test_missing_state_defaults_empty(self) -> None:
        """Missing 'State' in attrs defaults to empty string."""
        c = MagicMock()
        c.id = "abc123"
        c.name = "test"
        c.attrs = {}
        c.labels = {}

        info = container_info(c)
        assert info["status"] == ""

    def test_returns_all_fields(self) -> None:
        """Returned dict has id, name, status, labels."""
        c = MagicMock()
        c.id = "xyz789"
        c.name = "recorder-1"
        c.attrs = {"State": "created"}
        c.labels = {"io.silvasonic.owner": "controller"}

        info = container_info(c)
        assert info == {
            "id": "xyz789",
            "name": "recorder-1",
            "status": "created",
            "labels": {"io.silvasonic.owner": "controller"},
        }


# ===================================================================
# list_containers() / list_managed_containers()
# ===================================================================


@pytest.mark.unit
class TestSilvasonicPodmanClientListContainers:
    """Tests for list_containers() and list_managed_containers()."""

    def test_list_containers_returns_info(self) -> None:
        """Returns list of container dicts."""
        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_container.name = "silvasonic-recorder-mic1"
        mock_container.attrs = {"State": "running"}  # sparse mode
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
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = None

        assert client.list_containers() == []

    def test_list_containers_error(self) -> None:
        """Returns empty list on error."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.containers.list.side_effect = RuntimeError("boom")
        client._connected = True

        assert client.list_containers() == []

    def test_list_containers_connection_error(self) -> None:
        """Returns empty list on ConnectionError."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.containers.list.side_effect = ConnectionError("socket gone")
        client._connected = True

        assert client.list_containers() == []

    def test_list_containers_os_error(self) -> None:
        """Returns empty list on OSError."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.containers.list.side_effect = OSError("broken pipe")
        client._connected = True

        assert client.list_containers() == []

    def test_list_containers_with_filters(self) -> None:
        """list_containers passes filters to podman."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.containers.list.return_value = []
        client._connected = True

        client.list_containers(status=["running"])
        client._client.containers.list.assert_called_once_with(filters={"status": ["running"]})

    def test_list_managed_containers(self) -> None:
        """Filters by io.silvasonic.owner=controller label (default)."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.containers.list.return_value = []
        client._connected = True

        client.list_managed_containers()
        client._client.containers.list.assert_called_once_with(
            filters={"label": "io.silvasonic.owner=controller"}
        )

    def test_list_managed_containers_custom_profile(self) -> None:
        """Custom owner_profile changes the label filter."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = MagicMock()
        client._client.containers.list.return_value = []
        client._connected = True

        client.list_managed_containers(owner_profile="controller-test-abc12345")
        client._client.containers.list.assert_called_once_with(
            filters={"label": "io.silvasonic.owner=controller-test-abc12345"}
        )


# ===================================================================
# close()
# ===================================================================


@pytest.mark.unit
class TestSilvasonicPodmanClientClose:
    """Tests for close()."""

    def test_close_connected(self) -> None:
        """Calls client.close() and cleans up state."""
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
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = None
        client._connected = False

        client.close()  # Should not raise

    def test_close_handles_error(self) -> None:
        """Cleans up even when close() raises."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        mock_inner = MagicMock()
        mock_inner.close.side_effect = RuntimeError("cleanup failed")
        client._client = mock_inner
        client._connected = True

        client.close()

        assert client._client is None
        assert not client.is_connected


# ===================================================================
# containers property
# ===================================================================


@pytest.mark.unit
class TestSilvasonicPodmanClientContainersProperty:
    """Tests for the containers property."""

    def test_containers_when_connected(self) -> None:
        """Returns client.containers when connected."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        mock_inner = MagicMock()
        client._client = mock_inner
        client._connected = True

        assert client.containers is mock_inner.containers

    def test_containers_raises_when_not_connected(self) -> None:
        """Raises RuntimeError when client is None."""
        client = SilvasonicPodmanClient.__new__(SilvasonicPodmanClient)
        client._client = None
        client._connected = False

        with pytest.raises(RuntimeError, match="not connected"):
            _ = client.containers
