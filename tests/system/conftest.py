"""Shared fixtures for system and system_hw tests.

Provides:
- Testcontainers-based PostgreSQL and Redis (session-scoped).
- Real ``SilvasonicPodmanClient`` connected to the host Podman socket.
- ``ContainerManager`` with automatic cleanup of test containers.
- Async SQLAlchemy session factory wired to the testcontainers DB.
- Hardware mic config loading from profile YAMLs (env-var driven).
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import structlog
import yaml
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import Tier2ServiceSpec
from silvasonic.controller.podman_client import SilvasonicPodmanClient
from silvasonic.core.schemas.devices import MicrophoneProfile as MicProfileSchema
from silvasonic.test_utils.helpers import build_postgres_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Podman socket discovery (same pattern as test_crash_recovery.py)
# ---------------------------------------------------------------------------

_DEFAULT_ROOTLESS_SOCKET = f"/run/user/{os.getuid()}/podman/podman.sock"
PODMAN_SOCKET = os.environ.get("SILVASONIC_PODMAN_SOCKET", _DEFAULT_ROOTLESS_SOCKET)


def _is_podman_reachable() -> bool:
    """Check if the Podman engine is reachable.

    Uses ``podman info`` instead of ``Path.exists()`` because systemd
    socket-activated sockets are invisible to ``stat()`` /
    ``socket.connect()`` — the file lives in kernel space only
    (visible in ``/proc/net/unix`` but not in the filesystem).
    """
    import subprocess

    try:
        return (
            subprocess.run(
                ["podman", "info"],
                capture_output=True,
                timeout=5,
            ).returncode
            == 0
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


SOCKET_AVAILABLE = _is_podman_reachable()
RECORDER_IMAGE = "localhost/silvasonic_recorder:latest"


# Unique per pytest-session — appended to container names and labels so that
# parallel test runs and the production stack never interfere with each other.
TEST_RUN_ID = uuid.uuid4().hex[:8]


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


@pytest.fixture()
def hw_redis() -> Iterator[tuple[str, int, str]]:
    """Ephemeral Redis on an isolated network for hardware E2E tests.

    Creates its own isolated Podman network with a unique name per test
    session.  The Redis container gets alias ``silvasonic-redis`` so that
    Recorder containers can reach it at ``redis://silvasonic-redis:6379/0``
    within the isolated network.

    Yields ``(host_ip, mapped_port, network_name)`` — the network name is
    needed so the test can attach Recorder containers to the same network.
    """
    hw_network = f"silvasonic-hw-test-{TEST_RUN_ID}"
    container_name = f"silvasonic-redis-hwtest-{TEST_RUN_ID}"

    # Create isolated network for this HW test session
    subprocess.run(
        ["podman", "network", "create", hw_network],
        capture_output=True,
        timeout=10,
    )

    # Force-remove any stale container from a previous interrupted run
    subprocess.run(
        ["podman", "rm", "-f", container_name],
        capture_output=True,
        timeout=10,
    )

    # Start Redis with network alias + published port for host access
    result = subprocess.run(
        [
            "podman",
            "run",
            "-d",
            "--name",
            container_name,
            "--network",
            hw_network,
            "--network-alias",
            "silvasonic-redis",
            "-p",
            "6379",  # random host port (Podman syntax)
            "docker.io/library/redis:7-alpine",
            "redis-server",
            "--save",
            "",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Failed to start Redis container: exit {result.returncode}\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )

    try:
        # Wait for Redis to be ready
        for _ in range(20):
            ping = subprocess.run(
                ["podman", "exec", container_name, "redis-cli", "ping"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if ping.stdout.strip() == "PONG":
                break
            time.sleep(0.25)

        # Get mapped host port
        port_result = subprocess.run(
            ["podman", "port", container_name, "6379"],
            capture_output=True,
            text=True,
            check=True,
        )
        # Output like "0.0.0.0:12345"
        mapped_port = int(port_result.stdout.strip().split(":")[-1])

        yield ("127.0.0.1", mapped_port, hw_network)
    finally:
        with contextlib.suppress(Exception):
            subprocess.run(
                ["podman", "rm", "-f", container_name],
                capture_output=True,
                timeout=10,
            )
        with contextlib.suppress(Exception):
            subprocess.run(
                ["podman", "network", "rm", "-f", hw_network],
                capture_output=True,
                timeout=10,
            )


def make_test_spec(name: str, device_id: str, workspace: Path, *, network: str) -> Tier2ServiceSpec:
    """Create a minimal Recorder spec for system testing.

    Shared helper used by ``test_controller_lifecycle.py`` and
    ``test_crash_recovery.py`` to avoid duplicating spec construction.

    Args:
        name: Container name.
        device_id: Device ID label value.
        workspace: Host directory to bind-mount as workspace.
        network: Podman network to attach the container to.
            Each test must supply its own isolated network.

    The ``io.silvasonic.owner`` label is set to
    ``controller-test-<TEST_RUN_ID>`` so that test containers are invisible
    to the production Controller and to ``just stop``.
    """
    from silvasonic.controller.container_spec import (
        MountSpec,
        RestartPolicy,
        Tier2ServiceSpec,
    )

    spec = Tier2ServiceSpec(
        image=RECORDER_IMAGE,
        name=name,
        network=network,
        environment={
            "SILVASONIC_RECORDER_DEVICE": "hw:99,0",
            "SILVASONIC_RECORDER_PROFILE_SLUG": "test_profile",
            "SILVASONIC_REDIS_URL": "redis://silvasonic-redis:6379/0",
        },
        labels={
            "io.silvasonic.tier": "2",
            "io.silvasonic.owner": f"controller-test-{TEST_RUN_ID}",
            "io.silvasonic.service": "recorder",
            "io.silvasonic.device_id": device_id,
            "io.silvasonic.profile": "test_profile",
        },
        mounts=[
            MountSpec(
                source=str(workspace),
                target="/app/workspace",
                read_only=False,
            ),
        ],
        devices=[],
        group_add=[],
        privileged=False,
        restart_policy=RestartPolicy(name="no", max_retry_count=0),
        memory_limit="128m",
        cpu_limit=0.5,
        oom_score_adj=-999,
    )

    # Inject config drift hash for reconciliation system tests
    spec.labels["io.silvasonic.config_hash"] = spec.config_hash
    return spec


# ---------------------------------------------------------------------------
# Hardware Mic Config (env-var driven, profile-YAML backed)
# ---------------------------------------------------------------------------

# Path to the profiles directory (relative to the controller service root)
_PROFILES_DIR = (
    Path(__file__).resolve().parents[2] / "services" / "controller" / "config" / "profiles"
)


@dataclass(frozen=True)
class HwMicConfig:
    """Hardware mic configuration extracted from a profile YAML.

    Used by system_hw tests to identify connected devices by USB VID/PID,
    seed the correct profile into the test DB, and generate dynamic
    skip conditions and interactive prompts.
    """

    slug: str
    name: str
    vid: str
    pid: str
    alsa_contains: str
    sample_rate: int
    profile_data: dict[str, Any]


def load_hw_mic_config(profile_slug: str) -> HwMicConfig:
    """Load a profile YAML by slug and extract test-relevant fields.

    Args:
        profile_slug: Filename stem in ``config/profiles/`` (e.g. ``ultramic_384_evo``).

    Raises:
        FileNotFoundError: If no YAML file exists for the given slug.
        KeyError: If the YAML is missing required match criteria.
    """
    yml_path = _PROFILES_DIR / f"{profile_slug}.yml"
    if not yml_path.exists():
        msg = (
            f"Profile YAML not found: {yml_path}. "
            f"Available profiles: {[p.stem for p in _PROFILES_DIR.glob('*.yml')]}"
        )
        raise FileNotFoundError(msg)

    raw: dict[str, Any] = yaml.safe_load(yml_path.read_text(encoding="utf-8"))

    # Validate against Pydantic schema
    validated = MicProfileSchema(**raw)

    match = raw["audio"]["match"]
    return HwMicConfig(
        slug=validated.slug,
        name=validated.name,
        vid=match["usb_vendor_id"],
        pid=match["usb_product_id"],
        alsa_contains=match.get("alsa_name_contains", ""),
        sample_rate=validated.audio.sample_rate,
        profile_data=raw,
    )


# Load mic configs from environment variables
_PRIMARY_SLUG = os.environ.get("SILVASONIC_HW_PRIMARY_PROFILE", "ultramic_384_evo")
_SECONDARY_SLUG = os.environ.get("SILVASONIC_HW_SECONDARY_PROFILE", "")

PRIMARY_MIC: HwMicConfig = load_hw_mic_config(_PRIMARY_SLUG)
SECONDARY_MIC: HwMicConfig | None = load_hw_mic_config(_SECONDARY_SLUG) if _SECONDARY_SLUG else None


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

    Uses a test-specific ``owner_profile`` so that ``list_managed()`` only
    returns containers belonging to this pytest session.

    On teardown, any containers with ``io.silvasonic.owner=controller-test-*``
    label and a name containing ``-test-`` are force-removed.
    """
    owner = f"controller-test-{TEST_RUN_ID}"
    mgr = ContainerManager(podman_client, owner_profile=owner)
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
# Profile seeding helpers (config-driven)
# ---------------------------------------------------------------------------


def _write_profile_yml(profiles_dir: Path, mic: HwMicConfig) -> None:
    """Write a mic config's profile data as YAML into the profiles directory."""
    yml_path = profiles_dir / f"{mic.slug}.yml"
    yml_path.write_text(
        yaml.dump(mic.profile_data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def seed_primary_profile(tmp_path: Path) -> Path:
    """Create the primary mic profile YAML for test seeding.

    Returns the profiles directory path.
    """
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(exist_ok=True)
    _write_profile_yml(profiles_dir, PRIMARY_MIC)
    return profiles_dir


def seed_secondary_profile(tmp_path: Path) -> Path:
    """Create the secondary mic profile YAML for test seeding.

    Returns the profiles directory path.

    Raises:
        RuntimeError: If no secondary mic is configured.
    """
    if SECONDARY_MIC is None:
        msg = "No secondary mic configured (set SILVASONIC_HW_SECONDARY_PROFILE)"
        raise RuntimeError(msg)
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(exist_ok=True)
    _write_profile_yml(profiles_dir, SECONDARY_MIC)
    return profiles_dir


def seed_all_profiles(tmp_path: Path) -> Path:
    """Seed both primary and secondary (if configured) profiles.

    Returns the profiles directory path.
    """
    profiles_dir = seed_primary_profile(tmp_path)
    if SECONDARY_MIC is not None:
        _write_profile_yml(profiles_dir, SECONDARY_MIC)
    return profiles_dir


# Backward-compatible alias
def seed_test_profile(tmp_path: Path) -> Path:
    """Create the primary mic profile YAML (backward-compatible alias).

    Returns the profiles directory path.
    """
    return seed_primary_profile(tmp_path)


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


# ---------------------------------------------------------------------------
# Convenience fixtures (reduce boilerplate in test files)
# ---------------------------------------------------------------------------


@pytest.fixture()
async def seeded_db(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> async_sessionmaker[AsyncSession]:
    """Session factory with all profiles and defaults seeded.

    Combines ``seed_test_defaults()`` + ``seed_all_profiles()`` +
    ``ConfigSeeder`` + ``ProfileBootstrapper`` into a single fixture.
    Returns the session factory for further queries.
    """
    from silvasonic.controller.seeder import ConfigSeeder, ProfileBootstrapper

    defaults_path = seed_test_defaults(tmp_path)
    profiles_dir = seed_all_profiles(tmp_path)

    async with session_factory() as session:
        await ConfigSeeder(defaults_path=defaults_path).seed(session)
        await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
        await session.commit()

    return session_factory


@pytest.fixture(scope="module")
def usb_devices() -> list[Any]:
    """Cached USB device scan result (module-scoped).

    Calls ``DeviceScanner.scan_all()`` once per test module and caches
    the result.  Do NOT use in hot-plug tests where device state changes
    between tests.
    """
    from silvasonic.controller.device_scanner import DeviceScanner

    return DeviceScanner().scan_all()


@pytest.fixture()
def primary_device(usb_devices: list[Any]) -> Any:
    """Return the first connected primary mic device, or skip.

    Uses the module-scoped ``usb_devices`` fixture and filters by the
    primary mic's VID/PID from the environment configuration.
    """
    from silvasonic.controller.device_scanner import DeviceInfo

    found: list[DeviceInfo] = [
        d
        for d in usb_devices
        if d.usb_vendor_id == PRIMARY_MIC.vid and d.usb_product_id == PRIMARY_MIC.pid
    ]
    if not found:
        pytest.skip(f"Primary mic {PRIMARY_MIC.name} not connected")
    return found[0]


# ---------------------------------------------------------------------------
# Re-export shared Processor fixtures (pytest auto-discovers from conftest)
# ---------------------------------------------------------------------------
# These fixtures are defined in _processor_helpers.py and re-exported here
# so that both test_processor_lifecycle.py and test_processor_resilience.py
# can use them without direct fixture imports (which cause F811 lint errors).

from ._processor_helpers import (  # noqa: E402, F401
    run_id,
    system_db,
    system_network,
    system_redis,
)
