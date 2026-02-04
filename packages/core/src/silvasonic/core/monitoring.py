import shutil
from pathlib import Path

import psutil
from silvasonic.core.schemas.status import SystemResources


class ResourceMonitor:
    """Helper to collect system resource metrics."""

    def __init__(self, storage_path: str | Path | None = None):
        """Initialize the monitor with an optional storage path."""
        self.storage_path = Path(storage_path) if storage_path else None

    def get_usage(self) -> SystemResources | None:
        """Collect current resource usage. Returns None if collection fails."""
        try:
            process = psutil.Process()

            # Memory in MB
            mem_info = process.memory_info()
            memory_mb = round(mem_info.rss / 1024 / 1024, 2)

            # CPU
            # interval=None is non-blocking but requires subsequent calls to be accurate.
            # Ideally the service calls this periodically.
            cpu_percent = process.cpu_percent(interval=None)

            # Advanced metrics (available on most platforms but guarded)
            num_fds = process.num_fds() if hasattr(process, "num_fds") else None
            num_threads = process.num_threads() if hasattr(process, "num_threads") else None

            resources = SystemResources(
                cpu_percent=cpu_percent,
                memory_mb=memory_mb,
                storage_gb=None,
                storage_path=None,
                num_fds=num_fds,
                num_threads=num_threads,
            )

            if self.storage_path and self.storage_path.exists():
                usage = shutil.disk_usage(self.storage_path)
                # Used in GB
                used_gb = round(usage.used / 1024 / 1024 / 1024, 2)
                resources.storage_gb = used_gb
                resources.storage_path = str(self.storage_path)

            return resources
        except Exception:
            return None
