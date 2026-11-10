"""Unit tests for build_worker_spec factory function.

Covers the worker container spec builder (container_spec.py L310-389)
which previously had 0% unit test coverage.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from silvasonic.controller.container_spec import build_worker_spec
from silvasonic.controller.worker_registry import BackgroundWorker


def _make_worker(**overrides: object) -> BackgroundWorker:
    """Create a test BackgroundWorker with sensible defaults."""
    defaults = {
        "name": "birdnet",
        "image": "localhost/silvasonic_birdnet:latest",
        "memory_limit": "512m",
        "cpu_limit": 1.0,
        "oom_score_adj": 500,
        "needs_recorder_read_access": False,
        "needs_own_workspace": False,
    }
    defaults.update(overrides)
    return BackgroundWorker(**defaults)


@pytest.mark.unit
class TestBuildWorkerSpec:
    """Tests for the build_worker_spec factory."""

    @patch.dict(
        "os.environ",
        {
            "SILVASONIC_NETWORK": "test-net",
            "SILVASONIC_WORKSPACE_PATH": "/mnt/workspace",
            "SILVASONIC_REDIS_URL": "redis://test:6379/0",
        },
    )
    def test_basic_fields(self) -> None:
        """build_worker_spec populates name, image, network, limits."""
        worker = _make_worker()
        spec = build_worker_spec(worker)

        assert spec.name == "silvasonic-birdnet"
        assert spec.image == "localhost/silvasonic_birdnet:latest"
        assert spec.network == "test-net"
        assert spec.memory_limit == "512m"
        assert spec.cpu_limit == 1.0
        assert spec.oom_score_adj == 500

    @patch.dict(
        "os.environ",
        {
            "SILVASONIC_NETWORK": "test-net",
            "SILVASONIC_WORKSPACE_PATH": "/mnt/workspace",
            "SILVASONIC_REDIS_URL": "redis://test:6379/0",
        },
    )
    def test_recorder_read_access_mount(self) -> None:
        """Worker with needs_recorder_read_access gets RO mount."""
        worker = _make_worker(needs_recorder_read_access=True)
        spec = build_worker_spec(worker)

        ro_mounts = [m for m in spec.mounts if m.read_only]
        assert len(ro_mounts) == 1
        assert ro_mounts[0].target == "/data/recorder"
        assert "recorder" in ro_mounts[0].source

    @patch.dict(
        "os.environ",
        {
            "SILVASONIC_NETWORK": "test-net",
            "SILVASONIC_WORKSPACE_PATH": "/mnt/workspace",
            "SILVASONIC_REDIS_URL": "redis://test:6379/0",
        },
    )
    def test_own_workspace_mount(self) -> None:
        """Worker with needs_own_workspace gets RW mount."""
        worker = _make_worker(
            name="birdnet",
            needs_own_workspace=True,
        )
        spec = build_worker_spec(worker)

        rw_targets = {m.target for m in spec.mounts if not m.read_only}
        assert rw_targets == {"/data/birdnet", "/data/database"}

    @patch.dict(
        "os.environ",
        {
            "SILVASONIC_NETWORK": "test-net",
            "SILVASONIC_WORKSPACE_PATH": "/mnt/workspace",
            "SILVASONIC_REDIS_URL": "redis://test:6379/0",
        },
    )
    def test_database_directory_mount(self) -> None:
        """Every worker gets the database directory read-write (ADR-0037).

        SQLite writes its WAL and lock index beside the file, so the
        directory is mounted, not the file.
        """
        spec = build_worker_spec(_make_worker(name="birdnet"))

        db_mounts = [m for m in spec.mounts if m.target == "/data/database"]
        assert len(db_mounts) == 1
        assert db_mounts[0].source == "/mnt/workspace/database"
        assert db_mounts[0].read_only is False
        assert spec.environment["SILVASONIC_DB_PATH"] == "/data/database/silvasonic.db"
        assert not any(k.startswith("POSTGRES_") for k in spec.environment)

    @patch.dict(
        "os.environ",
        {
            "SILVASONIC_NETWORK": "test-net",
            "SILVASONIC_WORKSPACE_PATH": "/mnt/workspace",
            "SILVASONIC_REDIS_URL": "redis://test:6379/0",
        },
    )
    def test_config_hash_in_labels(self) -> None:
        """Drift-detection: config_hash must be set in labels."""
        worker = _make_worker()
        spec = build_worker_spec(worker)

        assert "io.silvasonic.config_hash" in spec.labels
        assert len(spec.labels["io.silvasonic.config_hash"]) == 12
