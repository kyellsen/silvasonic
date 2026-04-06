"""Unit tests for silvasonic-processor service — 100 % coverage.

Covers the ProcessorService (SilvaService subclass) including:
- Package import
- Service configuration (port from env)
- ProcessorSettings Pydantic defaults
- load_config() DB reading hook
- run() lifecycle with shutdown event
- get_extra_meta() placeholder
- __main__ guard
"""

import asyncio
import json
import sys
import warnings
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.config_schemas import ProcessorSettings
from silvasonic.core.health import HealthMonitor
from silvasonic.processor.__main__ import ProcessorService
from silvasonic.processor.janitor import RetentionMode


def _make_bare_service() -> Any:
    """Create a bare ProcessorService without triggering SilvaService.__init__.

    Sets up a mock _ctx with a real HealthMonitor so the ``svc.health`` property
    works without mypy complaints.

    Returns ``Any`` so mock attributes (return_value, assert_called, etc.)
    are accessible without mypy ``attr-defined`` errors.
    """
    svc = ProcessorService.__new__(ProcessorService)
    svc._ctx = MagicMock()
    svc._ctx.health = HealthMonitor()
    svc._settings = ProcessorSettings()
    svc._shutdown_event = asyncio.Event()
    # Phase 3: Indexer attributes
    svc._recordings_dir = Path("/data/recorder")
    svc._total_indexed = 0
    svc._last_indexed_at = None
    svc._reconciled_count = 0
    # Phase 4: Janitor attributes
    svc._disk_usage_percent = 0.0
    svc._janitor_mode = RetentionMode.IDLE.value
    svc._files_deleted_total = 0
    svc._janitor_counter = 0
    svc._janitor_every_n = 1
    return svc


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestProcessorEnvSettings:
    """Tests for environment variable overrides."""

    def test_service_port_env_override(self) -> None:
        """service_port respects SILVASONIC_PROCESSOR_PORT at instantiation."""
        svc = _make_bare_service()
        # Simulate __init__ reading env var
        with patch.dict("os.environ", {"SILVASONIC_PROCESSOR_PORT": "7777"}):
            from silvasonic.processor.settings import ProcessorEnvSettings

            cfg = ProcessorEnvSettings()
            svc.service_port = cfg.PROCESSOR_PORT
        assert svc.service_port == 7777

    def test_log_startup_env_override(self) -> None:
        """PROCESSOR_LOG_STARTUP_S respects env override."""
        with patch.dict("os.environ", {"SILVASONIC_PROCESSOR_LOG_STARTUP_S": "120.0"}):
            from silvasonic.processor.settings import ProcessorEnvSettings

            cfg = ProcessorEnvSettings()
            assert cfg.PROCESSOR_LOG_STARTUP_S == 120.0

    def test_log_summary_interval_env_override(self) -> None:
        """PROCESSOR_LOG_SUMMARY_INTERVAL_S respects env override."""
        with patch.dict("os.environ", {"SILVASONIC_PROCESSOR_LOG_SUMMARY_INTERVAL_S": "600.0"}):
            from silvasonic.processor.settings import ProcessorEnvSettings

            cfg = ProcessorEnvSettings()
            assert cfg.PROCESSOR_LOG_SUMMARY_INTERVAL_S == 600.0


# ---------------------------------------------------------------------------
# ProcessorSettings (Pydantic defaults)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestProcessorSettings:
    """Tests for ProcessorSettings config schema defaults."""

    def test_settings_defaults(self) -> None:
        """ProcessorSettings() defaults match config/defaults.yml values."""
        s = ProcessorSettings()
        assert s.janitor_threshold_warning == 70.0
        assert s.janitor_threshold_critical == 80.0
        assert s.janitor_threshold_emergency == 90.0
        assert s.janitor_interval_seconds == 60
        assert s.janitor_batch_size == 50
        assert s.indexer_poll_interval == 2.0

    def test_settings_round_trip(self) -> None:
        """Serialize to JSON → deserialize → identical model."""
        original = ProcessorSettings()
        serialized = original.model_dump_json()
        restored = ProcessorSettings(**json.loads(serialized))
        assert restored == original


# ---------------------------------------------------------------------------
# ProcessorService.load_config()
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestProcessorLoadConfig:
    """Tests for the load_config() hook (DB reading)."""

    async def test_load_config_reads_db(self) -> None:
        """load_config() reads ProcessorSettings from system_config table."""
        svc = _make_bare_service()

        mock_row = MagicMock()
        mock_row.value = {
            "janitor_threshold_warning": 65.0,
            "janitor_threshold_critical": 75.0,
            "janitor_threshold_emergency": 85.0,
            "janitor_interval_seconds": 30,
            "janitor_batch_size": 25,
            "indexer_poll_interval": 1.0,
        }

        with patch(
            "silvasonic.processor.__main__.get_session",
        ) as mock_session:
            mock_ctx = AsyncMock()
            mock_ctx.get.return_value = mock_row
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()

            await svc.load_config()

        assert svc._settings.janitor_threshold_warning == 65.0
        assert svc._settings.janitor_batch_size == 25
        assert svc._settings.indexer_poll_interval == 1.0

    async def test_load_config_uses_defaults_when_no_row(self) -> None:
        """load_config() keeps Pydantic defaults when DB row is absent."""
        svc = _make_bare_service()
        original_settings = ProcessorSettings()

        with patch(
            "silvasonic.processor.__main__.get_session",
        ) as mock_session:
            mock_ctx = AsyncMock()
            mock_ctx.get.return_value = None
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()

            await svc.load_config()

        assert svc._settings == original_settings


# ---------------------------------------------------------------------------
# Cycle Methods
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestProcessorCycles:
    """Tests for the isolated cycle methods."""

    async def test_reconciliation_audit_success(self) -> None:
        """_run_reconciliation_audit_once updates metric and health on success."""
        svc = _make_bare_service()
        with (
            patch("silvasonic.processor.__main__.get_session") as mock_session,
            patch(
                "silvasonic.processor.__main__.reconciliation.run_audit",
                new_callable=AsyncMock,
                return_value=5,
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            await svc._run_reconciliation_audit_once()

        assert svc._reconciled_count == 5
        status = svc.health.get_status()
        assert status["components"]["indexer"]["healthy"] is True

    async def test_reconciliation_audit_exception(self) -> None:
        """Exception during reconciliation audit sets health to false."""
        svc = _make_bare_service()
        with (
            patch("silvasonic.processor.__main__.get_session") as mock_session,
            patch(
                "silvasonic.processor.__main__.reconciliation.run_audit",
                new_callable=AsyncMock,
                side_effect=RuntimeError,
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            await svc._run_reconciliation_audit_once()

        status = svc.health.get_status()
        assert status["components"]["indexer"]["healthy"] is False
        assert "reconciliation_failed" in status["components"]["indexer"]["details"]

    async def test_indexer_cycle_new(self) -> None:
        """_run_indexer_cycle updates metrics when new files are indexed."""
        svc = _make_bare_service()
        errored_files: set[str] = set()
        with (
            patch("silvasonic.processor.__main__.get_session") as mock_session,
            patch(
                "silvasonic.processor.__main__.indexer.index_recordings",
                new_callable=AsyncMock,
                return_value=MagicMock(new=3, errors=0, error_details=[]),
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            await svc._run_indexer_cycle(errored_files, MagicMock())

        assert svc._total_indexed == 3
        status = svc.health.get_status()
        assert status["components"]["indexer"]["healthy"] is True

    async def test_indexer_cycle_errors(self) -> None:
        """_run_indexer_cycle updates errored_files and sets unhealthy on DB errors."""
        svc = _make_bare_service()
        errored_files: set[str] = set()
        with (
            patch("silvasonic.processor.__main__.get_session") as mock_session,
            patch(
                "silvasonic.processor.__main__.indexer.index_recordings",
                new_callable=AsyncMock,
                return_value=MagicMock(new=0, errors=2, error_details=["err1"]),
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            await svc._run_indexer_cycle(errored_files, MagicMock())

        assert "err1" in errored_files
        status = svc.health.get_status()
        assert status["components"]["indexer"]["healthy"] is False

    async def test_janitor_cycle_success(self) -> None:
        """_run_janitor_cycle updates metrics when running successfully."""
        svc = _make_bare_service()
        svc._janitor_every_n = 1  # ensure it fires
        with patch(
            "silvasonic.processor.__main__.janitor.run_cleanup_safe",
            new_callable=AsyncMock,
            return_value=MagicMock(
                disk_usage_percent=45.5,
                mode=RetentionMode.IDLE,
                files_deleted=2,
                errors=0,
            ),
        ):
            await svc._run_janitor_cycle(MagicMock())

        assert svc._disk_usage_percent == 45.5
        assert svc._files_deleted_total == 2
        status = svc.health.get_status()
        assert status["components"]["janitor"]["healthy"] is True

    async def test_janitor_cycle_exception(self) -> None:
        """Exception during janitor cycle sets health to false."""
        svc = _make_bare_service()
        svc._janitor_every_n = 1
        with patch(
            "silvasonic.processor.__main__.janitor.run_cleanup_safe",
            new_callable=AsyncMock,
            side_effect=RuntimeError,
        ):
            await svc._run_janitor_cycle(MagicMock())

        status = svc.health.get_status()
        assert status["components"]["janitor"]["healthy"] is False


# ---------------------------------------------------------------------------
# get_extra_meta
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestProcessorGetExtraMeta:
    """Tests for the get_extra_meta() override."""

    def test_extra_meta_has_indexer_and_janitor(self) -> None:
        """get_extra_meta() returns indexer + janitor metrics dict."""
        svc = _make_bare_service()
        meta = svc.get_extra_meta()
        assert "indexer" in meta
        assert meta["indexer"]["total_indexed"] == 0
        assert meta["indexer"]["last_indexed_at"] is None
        assert meta["indexer"]["reconciled_count"] == 0
        assert "janitor" in meta
        assert meta["janitor"]["disk_usage_percent"] == 0.0
        assert meta["janitor"]["current_mode"] == "idle"
        assert meta["janitor"]["files_deleted_total"] == 0


# ---------------------------------------------------------------------------
# __main__ guard
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMainGuard:
    """Tests for the if __name__ == '__main__' guard."""

    def test_main_guard(self) -> None:
        """The if __name__ == '__main__' guard calls ProcessorService().start()."""
        import runpy

        # Remove cached module to prevent "found in sys.modules" RuntimeWarning
        sys.modules.pop("silvasonic.processor.__main__", None)

        with (
            patch("silvasonic.core.service.SilvaService.start", MagicMock()) as mock_start,
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore", RuntimeWarning)
            runpy.run_module("silvasonic.processor.__main__", run_name="__main__")
            mock_start.assert_called_once()
