"""Integration tests for the Processor lifecycle components.

Ensures that the extracted standalone cycle methods introduced to replace
the infinite `run()` loop do not crash when interacting with a real database.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from silvasonic.core.database.session import _get_engine, _get_session_factory
from silvasonic.processor.__main__ import ProcessorService


@pytest.mark.integration
class TestProcessorLifecycle:
    """Verify ProcessorService lifecycle and configuration."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch: pytest.MonkeyPatch, station_db: Path) -> None:
        """Point the code under test at the test database."""
        _get_engine.cache_clear()
        _get_session_factory.cache_clear()
        monkeypatch.setenv("SILVASONIC_DB_PATH", str(station_db))

    async def test_processor_metrics_and_lifecycle(self, tmp_path: Path) -> None:
        """Verify service initializes, runs cycles, and updates metrics safely."""
        service = ProcessorService()
        service._recordings_dir = tmp_path

        # Test phase 1: Config loading works safely
        await service.load_config()

        # Test phase 2: Reconciliation Audit runs cleanly on an empty DB
        await service._run_reconciliation_audit_once()
        assert service._reconciled_count == 0

        # Test phase 3: Indexer runs cleanly
        errored_files: set[str] = set()
        await service._run_indexer_cycle(errored_files, MagicMock())

        # Test phase 4: Janitor runs cleanly
        service._janitor_counter = 1
        service._janitor_every_n = 1
        await service._run_janitor_cycle(MagicMock())

        # Verify heartbeat metrics are correctly accessible
        meta = service.get_extra_meta()

        assert "indexer" in meta
        assert meta["indexer"]["total_indexed"] == 0
        assert meta["indexer"]["reconciled_count"] == 0

        assert "janitor" in meta
        assert meta["janitor"]["files_deleted_total"] == 0
