"""Shared fixtures for system and system_hw tests.

Provides:
- Testcontainers-based PostgreSQL and Redis (session-scoped).
- Real ``SilvasonicPodmanClient`` connected to the host Podman socket.
- ``ContainerManager`` with automatic cleanup of test containers.
- Async SQLAlchemy session factory wired to the testcontainers DB.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.podman_client import SilvasonicPodmanClient
from silvasonic.test_utils.helpers import build_postgres_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

# ---------------------------------------------------------------------------
# Podman socket discovery (same pattern as test_crash_recovery.py)
# ---------------------------------------------------------------------------

_DEFAULT_ROOTLESS_SOCKET = f"/run/user/{os.getuid()}/podman/podman.sock"
PODMAN_SOCKET = os.environ.get("SILVASONIC_PODMAN_SOCKET", _DEFAULT_ROOTLESS_SOCKET)
SOCKET_AVAILABLE = pathlib.Path(PODMAN_SOCKET).exists()
RECORDER_IMAGE = "localhost/silvasonic_recorder:latest"


def require_podman_socket() -> None:
    """Skip the test if the Podman socket is not available."""
    if not SOCKET_AVAILABLE:
        pytest.skip(f"Podman socket not found at {PODMAN_SOCKET}")


def require_recorder_image() -> None:
    """Skip the test if the Recorder image is not built."""
    import subprocess

    result = subprocess.run(
        ["podman", "image", "exists", RECORDER_IMAGE],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip("Recorder image not built (run 'just build' first)")


# ---------------------------------------------------------------------------
# Podman client / ContainerManager fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def podman_client() -> Iterator[SilvasonicPodmanClient]:
    """Provide a real Podman client connected to the host socket.

    Skips automatically if the Podman socket is unavailable.
    """
    require_podman_socket()

    client = SilvasonicPodmanClient(
        socket_path=PODMAN_SOCKET,
        max_retries=2,
        retry_delay=0.5,
    )
    client.connect()
    yield client
    client.close()


@pytest.fixture()
def container_manager(
    podman_client: SilvasonicPodmanClient,
) -> Iterator[ContainerManager]:
    """Provide a ContainerManager that auto-cleans test containers.

    On teardown, any containers with ``io.silvasonic.owner=controller``
    label and a name containing ``-test-`` are force-removed.
    """
    mgr = ContainerManager(podman_client)
    yield mgr

    # Cleanup: force-remove any test containers we created
    with contextlib.suppress(Exception):
        managed = mgr.list_managed()
        for c in managed:
            name = str(c.get("name", ""))
            if "-test-" in name or "-system-test-" in name:
                mgr.stop(name, timeout=3)
                mgr.remove(name)


# ---------------------------------------------------------------------------
# DB session factory (async, wired to testcontainers)
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory(
    postgres_container: PostgresContainer,
) -> async_sessionmaker[AsyncSession]:
    """Provide an async session factory for the testcontainers DB.

    Uses the shared, session-scoped ``postgres_container`` fixture
    from the root ``conftest.py``.
    """
    url = build_postgres_url(postgres_container)
    engine = create_async_engine(url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Default config / profile helpers
# ---------------------------------------------------------------------------


def seed_test_profile(tmp_path: Path) -> Path:
    """Create a profile YAML matching UltraMic 384K via USB VID/PID.

    Returns the profiles directory path.
    """
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(exist_ok=True)
    (profiles_dir / "ultramic_test.yml").write_text(
        """\
schema_version: "1.0"
slug: ultramic_test
name: UltraMic EVO Test Profile
description: System test profile for UltraMic 384K EVO.
audio:
  sample_rate: 384000
  channels: 1
  format: S16LE
  match:
    usb_vendor_id: "0869"
    usb_product_id: "0389"
    alsa_name_contains: "UltraMic384K_EVO"
processing:
  gain_db: 0.0
  chunk_size: 4096
stream:
  raw_enabled: true
  processed_enabled: true
  live_stream_enabled: false
  segment_duration_s: 15
""",
        encoding="utf-8",
    )
    return profiles_dir


def seed_test_defaults(tmp_path: Path) -> Path:
    """Create a defaults.yml with auto_enrollment=true.

    Returns the path to defaults.yml.
    """
    defaults_path = tmp_path / "defaults.yml"
    defaults_path.write_text(
        """\
system:
  station_name: "System Test Station"
  auto_enrollment: true

auth:
  default_username: "admin"
  default_password: "testpass"
""",
        encoding="utf-8",
    )
    return defaults_path
