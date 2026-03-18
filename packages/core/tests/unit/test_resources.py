"""Unit tests for ResourceCollector, HostResourceCollector, and disk usage.

Covers per-process and host-level resource collection, storage metrics,
and error handling.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from silvasonic.core.resources import HostResourceCollector, ResourceCollector


@pytest.mark.unit
class TestResourceCollector:
    """Tests for per-process resource collection."""

    @patch("silvasonic.core.resources.psutil.Process")
    def test_collect_basic_metrics(self, mock_process_cls: MagicMock) -> None:
        """Collects CPU, memory, and thread count."""
        proc = MagicMock()
        proc.cpu_percent.return_value = 12.3
        proc.memory_info.return_value = MagicMock(rss=100 * 1024 * 1024)
        proc.num_threads.return_value = 4
        mock_process_cls.return_value = proc

        rc = ResourceCollector()
        result = rc.collect()

        assert result["cpu_percent"] == 12.3
        assert result["memory_mb"] == 100.0
        assert result["num_threads"] == 4

    @patch("silvasonic.core.resources.shutil.disk_usage")
    @patch("silvasonic.core.resources.psutil.Process")
    def test_collect_with_storage(
        self,
        mock_process_cls: MagicMock,
        mock_disk: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Includes storage metrics when workspace_path is set."""
        proc = MagicMock()
        proc.cpu_percent.return_value = 5.0
        proc.memory_info.return_value = MagicMock(rss=50 * 1024 * 1024)
        proc.num_threads.return_value = 2
        mock_process_cls.return_value = proc

        mock_disk.return_value = MagicMock(
            used=100 * 1024**3,
            total=500 * 1024**3,
        )

        rc = ResourceCollector(workspace_path=tmp_path)
        result = rc.collect()

        assert "storage_used_gb" in result
        assert "storage_total_gb" in result
        assert "storage_percent" in result
        assert result["storage_percent"] == 20.0

    @patch("silvasonic.core.resources.psutil.Process")
    def test_collect_handles_exception(self, mock_process_cls: MagicMock) -> None:
        """Returns empty dict on generic errors."""
        proc = MagicMock()
        proc.cpu_percent.side_effect = [0.0, RuntimeError("no process")]
        mock_process_cls.return_value = proc

        rc = ResourceCollector()
        result = rc.collect()

        assert result == {}

    @patch("silvasonic.core.resources.psutil.Process")
    def test_collect_handles_psutil_error(self, mock_process_cls: MagicMock) -> None:
        """Returns empty dict on psutil.Error (lines 105-107)."""
        import psutil

        proc = MagicMock()
        proc.cpu_percent.side_effect = [0.0, psutil.Error("no such process")]
        mock_process_cls.return_value = proc

        rc = ResourceCollector()
        result = rc.collect()

        assert result == {}


@pytest.mark.unit
class TestHostResourceCollector:
    """Tests for host-level resource collection (Controller)."""

    @patch("silvasonic.core.resources.psutil.cpu_count", return_value=4)
    @patch("silvasonic.core.resources.psutil.cpu_percent", return_value=23.5)
    @patch("silvasonic.core.resources.psutil.virtual_memory")
    def test_collect_host_metrics(
        self,
        mock_vmem: MagicMock,
        mock_cpu_pct: MagicMock,
        mock_cpu_cnt: MagicMock,
    ) -> None:
        """Collects host CPU, memory, and count."""
        mock_vmem.return_value = MagicMock(
            used=2048 * 1024 * 1024,
            total=8192 * 1024 * 1024,
            percent=25.0,
        )

        hrc = HostResourceCollector()
        result = hrc.collect()

        assert result["cpu_percent"] == 23.5
        assert result["cpu_count"] == 4
        assert result["memory_percent"] == 25.0

    @patch(
        "silvasonic.core.resources.psutil.cpu_percent",
        side_effect=RuntimeError,
    )
    def test_collect_handles_exception(self, mock_cpu: MagicMock) -> None:
        """Returns empty dict on generic errors."""
        hrc = HostResourceCollector()
        result = hrc.collect()
        assert result == {}

    @patch(
        "silvasonic.core.resources.psutil.cpu_percent",
        side_effect=OSError("filesystem error"),
    )
    def test_collect_handles_os_error(self, mock_cpu: MagicMock) -> None:
        """Returns empty dict on OSError (lines 152-154)."""
        hrc = HostResourceCollector()
        result = hrc.collect()
        assert result == {}

    @patch("silvasonic.core.resources._collect_disk_usage")
    @patch("silvasonic.core.resources.psutil.cpu_count", return_value=8)
    @patch("silvasonic.core.resources.psutil.cpu_percent", return_value=15.0)
    @patch("silvasonic.core.resources.psutil.virtual_memory")
    def test_collect_includes_storage(
        self,
        mock_vmem: MagicMock,
        mock_cpu_pct: MagicMock,
        mock_cpu_cnt: MagicMock,
        mock_disk: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Includes storage metrics when storage_path is set."""
        mock_vmem.return_value = MagicMock(
            used=4096 * 1024 * 1024,
            total=16384 * 1024 * 1024,
            percent=25.0,
        )
        mock_disk.return_value = (200.0, 1000.0, 20.0)

        hrc = HostResourceCollector(storage_path=tmp_path)
        result = hrc.collect()

        assert result["storage_used_gb"] == 200.0
        assert result["storage_total_gb"] == 1000.0
        assert result["storage_percent"] == 20.0


@pytest.mark.unit
class TestCollectDiskUsage:
    """Tests for _collect_disk_usage helper function."""

    def test_nonexistent_path_returns_none(self) -> None:
        """Returns None for paths that don't exist."""
        from silvasonic.core.resources import _collect_disk_usage

        result = _collect_disk_usage(Path("/nonexistent/path/should/not/exist"))
        assert result is None
