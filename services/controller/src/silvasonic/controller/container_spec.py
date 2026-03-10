"""Pydantic models for Tier 2 container specifications (ADR-0013, ADR-0020).

Defines the complete configuration needed to launch a Tier 2 container
via ``podman.containers.run()``, including resource limits, labels,
mounts, and restart policies.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field
from silvasonic.core.database.models.profiles import MicrophoneProfile as MicProfileDB
from silvasonic.core.database.models.system import Device


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------
class MountSpec(BaseModel):
    """Bind mount specification (ADR-0009: Zero-Trust mounts)."""

    source: str = Field(..., description="Host path")
    target: str = Field(..., description="Container path")
    read_only: bool = Field(default=False, description="Mount as read-only (consumer)")


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


# ---------------------------------------------------------------------------
# Factory: Recorder
# ---------------------------------------------------------------------------
# OOM score is a fixed architectural constant (ADR-0020), not configurable.
_RECORDER_OOM_SCORE_ADJ = -999  # Protected: OOM Killer kills this LAST


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
    # Read env vars at call time — not import time (Audit Z-1)
    network = network or os.environ.get("SILVASONIC_NETWORK", "silvasonic-net")
    workspace_path = workspace_path or os.environ.get(
        "SILVASONIC_WORKSPACE_PATH", "/mnt/data/workspace"
    )
    memory_limit = memory_limit or os.environ.get("SILVASONIC_RECORDER_MEMORY_LIMIT", "512m")
    if cpu_limit is None:
        cpu_limit = float(os.environ.get("SILVASONIC_RECORDER_CPU_LIMIT", "1.0"))

    device_id = device.name

    return Tier2ServiceSpec(
        image="silvasonic-recorder:latest",
        name=f"silvasonic-recorder-{device_id}",
        network=network,
        environment={
            "RECORDER_DEVICE": device.config.get("alsa_device", "hw:1,0"),
            "RECORDER_PROFILE": profile.slug,
            "SILVASONIC_REDIS_URL": os.environ.get(
                "SILVASONIC_REDIS_URL", "redis://localhost:6379/0"
            ),
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
                source=f"{workspace_path}/recorder/{device_id}",
                target="/app/workspace",
                read_only=False,  # Recorder is a producer → RW (ADR-0009)
            ),
        ],
        devices=["/dev/snd:/dev/snd"],
        group_add=["audio"],
        privileged=True,  # ADR-0007 §6
        memory_limit=memory_limit,
        cpu_limit=cpu_limit,
        oom_score_adj=_RECORDER_OOM_SCORE_ADJ,
    )
