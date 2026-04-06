"""Integration tests for the Processor lifecycle components.

Ensures that the extracted standalone cycle methods introduced to replace
the infinite `run()` loop do not crash when interacting with a real database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from silvasonic.core.database.session import _get_engine, _get_session_factory
from silvasonic.processor.__main__ import ProcessorService
from testcontainers.postgres import PostgresContainer


@pytest.mark.integration
class TestProcessorLifecycle:
    """Verify ProcessorService lifecycle and configuration."""

    @pytest.fixture(autouse=True)
    def setup_env(
        self, monkeypatch: pytest.MonkeyPatch, postgres_container: PostgresContainer
    ) -> None:
        """Inject testcontainer DB credentials into environment."""
        _get_engine.cache_clear()
        _get_session_factory.cache_clear()
        monkeypatch.setenv("SILVASONIC_DB_HOST", postgres_container.get_container_host_ip())
        monkeypatch.setenv("SILVASONIC_DB_PORT", str(postgres_container.get_exposed_port(5432)))
        monkeypatch.setenv("POSTGRES_USER", "silvasonic")
        monkeypatch.setenv("POSTGRES_PASSWORD", "silvasonic")
        monkeypatch.setenv("POSTGRES_DB", "silvasonic_test")

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
        await service._run_indexer_cycle(errored_files)

        # Test phase 4: Janitor runs cleanly
        service._janitor_counter = 1
        service._janitor_every_n = 1
        await service._run_janitor_cycle()

        # Verify heartbeat metrics are correctly accessible
        meta = service.get_extra_meta()

        assert "indexer" in meta
        assert meta["indexer"]["total_indexed"] == 0
        assert meta["indexer"]["reconciled_count"] == 0

        assert "janitor" in meta
        assert meta["janitor"]["files_deleted_total"] == 0
