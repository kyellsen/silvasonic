import time
from typing import Any, Literal

from pydantic import BaseModel, Field


class StatusHeader(BaseModel):
    """Header for status messages."""

    topic: Literal["status"] = "status"
    service: str
    instance_id: str
    timestamp: float = Field(default_factory=time.time)


class SystemResources(BaseModel):
    """System resource usage metrics."""

    cpu_percent: float = Field(..., description="System-wide CPU usage percentage")
    memory_mb: float = Field(..., description="RSS memory usage in MB")
    storage_gb: float | None = Field(None, description="Used storage in GB (if applicable)")
    storage_path: str | None = Field(None, description="Path being monitored for storage")
    num_fds: int | None = Field(None, description="Number of open file descriptors")
    num_threads: int | None = Field(None, description="Number of active threads")


class StatusPayloadContent(BaseModel):
    """Content payload for status messages."""

    health: Literal["healthy", "degraded"]
    activity: str
    progress: float | None = None
    message: str
    # New standardized resources field
    resources: SystemResources | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class StatusMessage(StatusHeader):
    """Complete status message."""

    payload: StatusPayloadContent


class LifecycleHeader(BaseModel):
    """Header for lifecycle messages."""

    topic: Literal["lifecycle"] = "lifecycle"
    event: Literal["started", "stopping", "crashed"]
    service: str
    instance_id: str
    timestamp: float = Field(default_factory=time.time)


class LifecyclePayloadContent(BaseModel):
    """Content payload for lifecycle messages."""

    version: str | None = None
    pid: int | None = None
    reason: str | None = None


class LifecycleMessage(LifecycleHeader):
    """Complete lifecycle message."""

    payload: LifecyclePayloadContent
