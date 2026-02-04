from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from silvasonic.core.monitoring import ResourceMonitor
from silvasonic.core.schemas.status import SystemResources


@pytest.fixture
def mock_psutil() -> Generator[MagicMock, None, None]:
    with patch("silvasonic.core.monitoring.psutil") as mock:
        process = MagicMock()
        process.cpu_percent.return_value = 15.5
        process.memory_info.return_value.rss = 104857600  # 100 MB
        process.num_fds.return_value = 42
        process.num_threads.return_value = 12
        mock.Process.return_value = process
        yield mock


@pytest.fixture
def mock_shutil() -> Generator[MagicMock, None, None]:
    with patch("silvasonic.core.monitoring.shutil") as mock:
        mock.disk_usage.return_value.used = 53687091200  # 50 GB
        yield mock


def test_monitoring_basic(mock_psutil: MagicMock) -> None:
    """Test basic CPU and Memory monitoring."""
    monitor = ResourceMonitor()
    usage = monitor.get_usage()

    assert usage is not None
    assert isinstance(usage, SystemResources)
    assert usage.cpu_percent == 15.5
    assert usage.memory_mb == 100.0
    assert usage.num_fds == 42
    assert usage.num_threads == 12
    assert usage.storage_gb is None
    assert usage.storage_path is None


def test_monitoring_with_storage(
    mock_psutil: MagicMock, mock_shutil: MagicMock, tmp_path: Path
) -> None:
    """Test monitoring with storage path."""
    monitor = ResourceMonitor(storage_path=tmp_path)
    usage = monitor.get_usage()

    assert usage is not None
    assert isinstance(usage, SystemResources)
    assert usage.cpu_percent == 15.5
    assert usage.memory_mb == 100.0
    assert usage.storage_gb == 50.0  # 50GB
    assert str(usage.storage_path) == str(tmp_path)
    assert usage.num_fds == 42
    assert usage.num_threads == 12


def test_monitoring_invalid_path(mock_psutil: MagicMock) -> None:
    """Test that non-existent path is ignored safely."""
    monitor = ResourceMonitor(storage_path="/non/existent/path/123")
    usage = monitor.get_usage()

    assert usage is not None
    assert usage.storage_gb is None


def test_monitoring_failsafe(mock_psutil: MagicMock) -> None:
    """Test that exceptions during collection return None instead of crashing."""
    mock_psutil.Process.side_effect = Exception("Psutil crash")

    monitor = ResourceMonitor()
    usage = monitor.get_usage()

    assert usage is None
