"""Pydantic models for Tier 2 container specifications (ADR-0013, ADR-0020).

Defines the complete configuration needed to launch a Tier 2 container
via ``podman.containers.run()``, including resource limits, labels,
mounts, and restart policies.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from silvasonic.core.database.models.profiles import MicrophoneProfile as MicProfileDB
from silvasonic.core.database.models.system import Device


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------
class MountSpec(BaseModel):
    """Bind mount specification (ADR-0009: Zero-Trust mounts)."""

    source: str = Field(..., description="Host path (passed to Podman for spawned container)")
    target: str = Field(..., description="Container path")
    read_only: bool = Field(default=False, description="Mount as read-only (consumer)")
    controller_source: str | None = Field(
        default=None,
        description="Controller-local path for mkdir (maps to host via bind mount)",
    )


class RestartPolicy(BaseModel):
    """Container restart policy (ADR-0013)."""

    name: str = Field(default="on-failure", description="Restart strategy")
    max_retry_count: int = Field(default=5, description="Maximum restart attempts")


# ---------------------------------------------------------------------------
# Tier2ServiceSpec
# ---------------------------------------------------------------------------
class Tier2ServiceSpec(BaseModel):
    """Complete specification for a Tier 2 container (ADR-0013, ADR-0020).

    Every field maps directly to a ``podman.containers.run()`` parameter.
    Resource limits (``memory_limit``, ``cpu_limit``, ``oom_score_adj``)
    are **mandatory** per ADR-0020.
    """

    image: str = Field(..., description="Container image (e.g., 'silvasonic-recorder:latest')")
    name: str = Field(..., description="Container name (e.g., 'silvasonic-recorder-mic1')")
    network: str = Field(..., description="Network name (from SILVASONIC_NETWORK)")
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables (Profile Injection, ADR-0013)",
    )
    labels: dict[str, str] = Field(
        default_factory=dict,
        description="Container labels for ownership and reconciliation",
    )
    mounts: list[MountSpec] = Field(
        default_factory=list,
        description="Bind mounts with RO/RW (ADR-0009)",
    )
    devices: list[str] = Field(
        default_factory=list,
        description="Device mappings (e.g., ['/dev/snd:/dev/snd'])",
    )
    group_add: list[str] = Field(
        default_factory=list,
        description="Additional groups (e.g., ['audio'])",
    )
    privileged: bool = Field(
        default=False,
        description="Privileged mode (ADR-0007 §6: Recorder = True)",
    )
    restart_policy: RestartPolicy = Field(
        default_factory=RestartPolicy,
        description="Restart policy (on-failure, max 5)",
    )

    # Resource Limits — MANDATORY (ADR-0020)
    memory_limit: str = Field(..., description="Memory limit (e.g., '512m', '1g')")
    cpu_limit: float = Field(..., description="CPU limit (e.g., 1.0 = 1 core)")
    oom_score_adj: int = Field(..., description="OOM priority (-999=protected, 500=expendable)")

    @property
    def config_hash(self) -> str:
        """Deterministic sha256 hash of the container configuration.

        Excludes labels, enabling the system to detect when a container's
        hardware mapping or environment has drifted (e.g., ALSA index change).
        """
        import hashlib

        data = self.model_dump(exclude={"labels"}, mode="json")
        payload = json.dumps(data, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Factory: Recorder
# ---------------------------------------------------------------------------
# OOM score is a fixed architectural constant (ADR-0020), not configurable.
_RECORDER_OOM_SCORE_ADJ = -999  # Protected: OOM Killer kills this LAST


class RecorderEnvConfig(BaseSettings):
    """Environment-based defaults for Recorder container specs."""

    model_config = SettingsConfigDict(env_prefix="SILVASONIC_")

    NETWORK: str = "silvasonic-net"
    WORKSPACE_PATH: str = "/mnt/data/workspace"
    RECORDER_MEMORY_LIMIT: str = "512m"
    RECORDER_CPU_LIMIT: float = 1.0
    RECORDER_WORKSPACE_LOCAL: str | None = None
    REDIS_URL: str = "redis://localhost:6379/0"

    # Container image for Recorder instances
    RECORDER_IMAGE: str = "localhost/silvasonic_recorder:latest"

    # Maximum restart attempts for the Podman restart policy (Level 2 recovery).
    # After this many consecutive failures, Podman stops restarting the container.
    # Range: 1-20.  Default 5.
    RECORDER_RESTART_MAX_RETRIES: int = 5


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _short_suffix(device: Device) -> str:
    """Derive a short, unique suffix from the device's hardware identity.

    Priority:
    1. Last 4 hex chars of USB serial — globally unique per device.
    2. USB bus path (dots/hyphens replaced) — unique per physical port.
    3. ALSA card index — fallback (unstable across reboots).

    Returns:
        4-character lowercase string, e.g. ``"034f"``, ``"p1d3"``, ``"c002"``.
    """
    serial = device.config.get("usb_serial", "") or ""
    if serial:
        return serial[-4:].lower()

    bus = device.config.get("usb_bus_path", "") or ""
    if bus:
        # "1-3.2" → "p1d3" (p=port, d=delimiter replacement)
        return ("p" + bus.replace("-", "d").replace(".", "d"))[:4]

    card_idx = device.config.get("alsa_card_index", 0)
    return f"c{card_idx:03d}"


def generate_workspace_name(profile_slug: str, device: Device) -> str:
    """Generate a human-readable workspace directory name.

    Combines the profile slug with a short hardware-derived suffix.
    This name is used as the Recorder workspace directory on disk
    and stored in ``devices.workspace_name`` for the Processor Indexer
    to resolve ``sensor_id`` from filesystem paths.

    Examples::

        >>> generate_workspace_name("ultramic_384_evo", device_with_serial)
        'ultramic-384-evo-034f'
        >>> generate_workspace_name("rode_nt_usb", device_with_bus_path)
        'rode-nt-usb-p3d6'

    Args:
        profile_slug: Microphone profile slug (e.g. ``"ultramic_384_evo"``).
        device: Device row with ``config`` containing hardware identity.

    Returns:
        Podman-safe, human-readable name (lowercase alphanumeric + hyphens).
    """
    safe_slug = _SLUG_RE.sub("-", profile_slug.lower()).strip("-")
    safe_suffix = _SLUG_RE.sub("", _short_suffix(device).lower())
    return f"{safe_slug}-{safe_suffix}"


def _container_name(profile_slug: str, suffix: str) -> str:
    """Build a Podman-safe, human-readable container name.

    Format: ``silvasonic-recorder-{slug}-{suffix}``

    Slug is lowercased and stripped of non-alphanumeric characters
    (underscores/special chars replaced by hyphens, consecutive hyphens
    collapsed).

    Examples::

        >>> _container_name("ultramic_384_evo", "034f")
        'silvasonic-recorder-ultramic-384-evo-034f'

    Returns:
        Valid Podman container name (lowercase alphanumeric + hyphens).
    """
    safe_slug = _SLUG_RE.sub("-", profile_slug.lower()).strip("-")
    safe_suffix = _SLUG_RE.sub("", suffix.lower())
    return f"silvasonic-recorder-{safe_slug}-{safe_suffix}"


def build_recorder_spec(
    device: Device,
    profile: MicProfileDB,
    *,
    network: str | None = None,
    workspace_path: str | None = None,
    memory_limit: str | None = None,
    cpu_limit: float | None = None,
) -> Tier2ServiceSpec:
    """Build a ``Tier2ServiceSpec`` for a Recorder instance.

    Environment variables are read at **call time** (not import time)
    so that ``monkeypatch.setenv()`` works in tests without module reload.

    Args:
        device: Device row from the ``devices`` table.
        profile: MicrophoneProfile row from the ``microphone_profiles`` table.
        network: Override for ``SILVASONIC_NETWORK`` (default from env).
        workspace_path: Override for ``SILVASONIC_WORKSPACE_PATH`` (default from env).
        memory_limit: Override for ``SILVASONIC_RECORDER_MEMORY_LIMIT`` (default from env).
        cpu_limit: Override for ``SILVASONIC_RECORDER_CPU_LIMIT`` (default from env).

    Returns:
        Complete spec ready for ``ContainerManager.start()``.
    """
    # Read env vars via Pydantic BaseSettings (validated, type-safe)
    env = RecorderEnvConfig()
    network = network or env.NETWORK
    workspace_path = workspace_path or env.WORKSPACE_PATH
    memory_limit = memory_limit or env.RECORDER_MEMORY_LIMIT
    if cpu_limit is None:
        cpu_limit = env.RECORDER_CPU_LIMIT

    # Controller-local workspace path (for mkdir inside the controller container).
    # In container: SILVASONIC_RECORDER_WORKSPACE_LOCAL=/app/recorder-workspace
    # In tests/dev: falls back to workspace_path/recorder (direct host path).
    recorder_local = env.RECORDER_WORKSPACE_LOCAL or str(Path(workspace_path) / "recorder")

    device_id = device.name
    workspace_dir = generate_workspace_name(profile.slug, device)
    container_name = f"silvasonic-recorder-{workspace_dir}"

    spec = Tier2ServiceSpec(
        image=env.RECORDER_IMAGE,
        name=container_name,
        network=network,
        environment={
            "SILVASONIC_RECORDER_DEVICE": device.config.get("alsa_device", "hw:1,0"),
            "SILVASONIC_RECORDER_PROFILE_SLUG": profile.slug,
            "SILVASONIC_RECORDER_CONFIG_JSON": json.dumps(profile.config),
            "SILVASONIC_REDIS_URL": env.REDIS_URL,
            "SILVASONIC_INSTANCE_ID": device_id,
            # Force PortAudio to use raw ALSA (not PulseAudio/PipeWire).
            # Prevents "Invalid sample rate" errors on hosts with desktop
            # audio stacks that cannot handle high sample rates (384kHz).
            "PULSE_SERVER": "",
            "PIPEWIRE_RUNTIME_DIR": "",
        },
        labels={
            "io.silvasonic.tier": "2",
            "io.silvasonic.owner": "controller",
            "io.silvasonic.service": "recorder",
            "io.silvasonic.device_id": device_id,
            "io.silvasonic.profile": profile.slug,
        },
        mounts=[
            MountSpec(
                source=str(Path(workspace_path) / "recorder" / workspace_dir),
                target="/app/workspace",
                read_only=False,  # Recorder is a producer → RW (ADR-0009)
                controller_source=str(Path(recorder_local) / workspace_dir),
            ),
        ],
        devices=["/dev/snd:/dev/snd"],
        group_add=["audio"],
        privileged=True,  # ADR-0007 §6
        restart_policy=RestartPolicy(max_retry_count=env.RECORDER_RESTART_MAX_RETRIES),
        memory_limit=memory_limit,
        cpu_limit=cpu_limit,
        oom_score_adj=_RECORDER_OOM_SCORE_ADJ,
    )

    # Inject config hash into labels for drift detection
    spec.labels["io.silvasonic.config_hash"] = spec.config_hash
    return spec
