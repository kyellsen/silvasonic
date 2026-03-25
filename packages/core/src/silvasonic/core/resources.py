"""Resource monitoring for Silvasonic services (ADR-0019).

Collects per-process CPU, memory, and thread metrics via ``psutil``.
Optionally collects storage usage for a given workspace path.

The ``ResourceCollector`` is used internally by ``SilvaService`` to
populate the ``meta.resources`` field of heartbeat payloads.  The
``HostResourceCollector`` extends this with host-level metrics
(total CPU/RAM/disk) for use by the Controller.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()


class ProcessResources(BaseModel):
    """Per-process resource metrics included in every heartbeat."""

    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    num_threads: int = 0
    storage_used_gb: float | None = None
    storage_total_gb: float | None = None
    storage_percent: float | None = None


class HostResources(BaseModel):
    """Host-level resource metrics (Controller only)."""

    cpu_percent: float = 0.0
    cpu_count: int = 1
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    memory_percent: float = 0.0
    storage_used_gb: float | None = None
    storage_total_gb: float | None = None
    storage_percent: float | None = None


def _collect_disk_usage(path: Path) -> tuple[float, float, float] | None:
    """Return (used_gb, total_gb, percent) for *path*, or None."""
    if not path.exists():
        return None
    usage = shutil.disk_usage(path)
    return (
        round(usage.used / 1024**3, 2),
        round(usage.total / 1024**3, 2),
        round(usage.used / usage.total * 100, 1),
    )


def _safe_collect(label: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run *fn* and return its result, returning {} on any error."""
    try:
        return fn()
    except (psutil.Error, OSError) as exc:
        logger.debug(f"{label}_failed", error=type(exc).__name__)
        return {}
    except Exception:
        logger.debug(f"{label}_failed", exc_info=True)
        return {}


class ResourceCollector:
    """Collects per-process resource metrics.

    Instantiated once by ``SilvaService`` and called on every heartbeat
    cycle to populate ``meta.resources``.

    Args:
        workspace_path: Optional path for storage monitoring (e.g. recordings dir).
    """

    def __init__(self, workspace_path: str | Path | None = None) -> None:
        """Initialize the resource collector."""
        self._workspace = Path(workspace_path) if workspace_path else None
        self._process = psutil.Process()
        # Prime cpu_percent (first call always returns 0.0)
        self._process.cpu_percent(interval=None)

    def collect(self) -> dict[str, Any]:
        """Collect current per-process resource usage."""

        def _inner() -> dict[str, Any]:
            resources = ProcessResources(
                cpu_percent=round(self._process.cpu_percent(interval=None), 1),
                memory_mb=round(self._process.memory_info().rss / 1024 / 1024, 2),
                num_threads=self._process.num_threads(),
            )
            if self._workspace is not None:
                disk = _collect_disk_usage(self._workspace)
                if disk is not None:
                    (
                        resources.storage_used_gb,
                        resources.storage_total_gb,
                        resources.storage_percent,
                    ) = disk
            return resources.model_dump(exclude_none=True)

        return _safe_collect("resource_collection", _inner)


class HostResourceCollector:
    """Collects host-level resource metrics (Controller only).

    Provides system-wide CPU, memory, and storage utilization for the
    Web-Interface dashboard.

    Args:
        storage_path: Path for host storage monitoring (typically SILVASONIC_WORKSPACE_PATH).
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        """Initialize the host resource collector."""
        self._storage_path = Path(storage_path) if storage_path else None

    def collect(self) -> dict[str, Any]:
        """Collect host-level resource metrics."""

        def _inner() -> dict[str, Any]:
            mem = psutil.virtual_memory()
            resources = HostResources(
                cpu_percent=round(psutil.cpu_percent(interval=None), 1),
                cpu_count=psutil.cpu_count(logical=True) or 1,
                memory_used_mb=round(mem.used / 1024 / 1024, 1),
                memory_total_mb=round(mem.total / 1024 / 1024, 1),
                memory_percent=round(mem.percent, 1),
            )
            if self._storage_path is not None:
                disk = _collect_disk_usage(self._storage_path)
                if disk is not None:
                    (
                        resources.storage_used_gb,
                        resources.storage_total_gb,
                        resources.storage_percent,
                    ) = disk
            return resources.model_dump(exclude_none=True)

        return _safe_collect("host_resource_collection", _inner)
