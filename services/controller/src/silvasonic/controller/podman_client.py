"""Podman client wrapper for Tier 2 container management (ADR-0013).

Provides a managed connection to the host Podman engine via the
mounted Unix socket.  Includes retry logic for startup scenarios
where the socket may not be available immediately.

Usage::

    client = SilvasonicPodmanClient()
    client.connect()          # blocks, retries up to MAX_RETRIES
    assert client.ping()
    containers = client.list_containers()
    client.close()
"""

from __future__ import annotations

import os
import time
from typing import Any

import structlog

log = structlog.get_logger()

# Defaults ────────────────────────────────────────────────────────────────────
DEFAULT_SOCKET_PATH = "/var/run/container.sock"
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 2.0


class PodmanConnectionError(Exception):
    """Raised when the Podman socket cannot be reached after retries."""


def _container_info(c: Any) -> dict[str, object]:
    """Extract standard info dict from a Podman container object.

    Handles podman-py sparse mode (default in v5.7+) where ``attrs["State"]``
    is a plain string (e.g. ``"running"``) instead of a dict
    ``{"Status": "running"}``.
    """
    # Podman API may prefix names with "/" — normalize for consistent matching.
    name = c.name.lstrip("/") if isinstance(c.name, str) else c.name

    # In sparse mode (default), attrs["State"] is a string like "running".
    # In full mode, attrs["State"] is a dict like {"Status": "running"}.
    # c.status accesses attrs["State"]["Status"] which crashes in sparse mode.
    state = c.attrs.get("State", "")
    status = state if isinstance(state, str) else state.get("Status", "unknown")

    return {"id": c.id, "name": name, "status": status, "labels": c.labels}


class SilvasonicPodmanClient:
    """Managed Podman client with reconnect logic.

    Wraps ``podman.PodmanClient`` and adds:

    * Retry-based ``connect()`` (up to *MAX_RETRIES* x *RETRY_DELAY_SECONDS*).
    * ``ping()`` — returns ``True``/``False`` without raising.
    * ``list_containers()`` — thin wrapper with sensible defaults.
    * ``close()`` — safe disconnect.

    The socket path is read from the ``SILVASONIC_CONTAINER_SOCKET`` environment
    variable (set in ``compose.yml``), falling back to
    ``/var/run/container.sock``.
    """

    def __init__(
        self,
        socket_path: str | None = None,
        max_retries: int = MAX_RETRIES,
        retry_delay: float = RETRY_DELAY_SECONDS,
    ) -> None:
        """Initialize with socket path and retry configuration.

        Args:
            socket_path: Path to the Podman socket.  Defaults to
                ``SILVASONIC_CONTAINER_SOCKET`` env var or ``/var/run/container.sock``.
            max_retries: Number of connection attempts before giving up.
            retry_delay: Seconds to wait between retries.
        """
        self._socket_path = socket_path or os.environ.get(
            "SILVASONIC_CONTAINER_SOCKET", DEFAULT_SOCKET_PATH
        )
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._client: Any = None  # podman.PodmanClient instance
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Return ``True`` if the client is connected and healthy."""
        return self._connected

    @property
    def socket_url(self) -> str:
        """Return the ``unix://`` URL used for the Podman socket."""
        return f"unix://{self._socket_path}"

    @property
    def socket_path(self) -> str:
        """Return the filesystem path to the Podman socket."""
        return self._socket_path

    @property
    def containers(self) -> Any:
        """Expose the Podman containers API.

        Raises:
            RuntimeError: If not connected (call ``connect()`` first).
        """
        if self._client is None:
            msg = "PodmanClient is not connected — call connect() first"
            raise RuntimeError(msg)
        return self._client.containers

    def connect(self) -> None:
        """Connect to the Podman socket with retry logic.

        Attempts up to ``max_retries`` times with ``retry_delay`` seconds
        between attempts.  On success, ``is_connected`` is ``True``.

        Raises:
            PodmanConnectionError: If all retries are exhausted.
        """
        from podman import PodmanClient

        for attempt in range(1, self._max_retries + 1):
            try:
                log_fn = log.info if attempt == 1 else log.debug
                log_fn(
                    "podman.connecting",
                    socket=self._socket_path,
                    attempt=attempt,
                    max_retries=self._max_retries,
                )
                client = PodmanClient(base_url=self.socket_url)
                if client.ping():
                    self._client = client
                    self._connected = True
                    log.info("podman.connected", socket=self._socket_path)
                    return
                msg = "Podman ping returned False"
                raise ConnectionError(msg)
            except Exception as e:
                expected = isinstance(e, (ConnectionError, OSError))
                log.warning(
                    "podman.connect_failed",
                    socket=self._socket_path,
                    attempt=attempt,
                    max_retries=self._max_retries,
                    error_type=type(e).__name__,
                    exc_info=not expected,
                )
                if attempt < self._max_retries:
                    time.sleep(self._retry_delay)

        self._connected = False
        msg = (
            f"Failed to connect to Podman socket at {self._socket_path} "
            f"after {self._max_retries} attempts"
        )
        raise PodmanConnectionError(msg)

    def ping(self) -> bool:
        """Check if the Podman engine is reachable.

        Returns:
            ``True`` if the engine responds, ``False`` otherwise.
        """
        if self._client is None:
            return False
        try:
            result: bool = self._client.ping()
            self._connected = result
            return result
        except (ConnectionError, OSError):
            self._connected = False
            return False
        except Exception as e:
            log.warning("podman.ping_failed", error_type=type(e).__name__)
            self._connected = False
            return False

    def list_containers(self, **filters: object) -> list[dict[str, object]]:
        """List containers, optionally filtered.

        Args:
            **filters: Passed as ``filters`` kwarg to
                ``podman.containers.list()``.

        Returns:
            List of container info dicts.  Empty list if not connected.
        """
        if self._client is None:
            return []
        try:
            containers = self._client.containers.list(filters=filters if filters else None)
            return [_container_info(c) for c in containers]
        except Exception as e:
            expected = isinstance(e, (ConnectionError, OSError))
            log.warning(
                "podman.list_containers_failed",
                error_type=type(e).__name__,
                exc_info=not expected,
            )
            return []

    def list_managed_containers(self) -> list[dict[str, object]]:
        """List containers owned by this Controller.

        Convenience method that filters by
        ``io.silvasonic.owner=controller``.

        Returns:
            List of managed container info dicts.
        """
        return self.list_containers(label="io.silvasonic.owner=controller")

    def close(self) -> None:
        """Disconnect from the Podman socket."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                log.debug("podman.close_error")
            finally:
                self._client = None
                self._connected = False
                log.info("podman.disconnected")
