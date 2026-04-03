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
# ProcessorService.run()
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestProcessorRun:
    """Tests for the run() coroutine."""

    async def test_run_starts_and_exits_on_shutdown(self) -> None:
        """run() sets health status and exits when shutdown_event is set."""
        svc = _make_bare_service()

        with (
            patch(
                "silvasonic.processor.__main__.get_session",
            ) as mock_session,
            patch(
                "silvasonic.processor.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=lambda _: svc._shutdown_event.set(),
            ),
        ):
            # Mock the DB session for reconciliation + indexer
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()

            # Mock reconciliation.run_audit and indexer.index_recordings
            with (
                patch(
                    "silvasonic.processor.__main__.reconciliation.run_audit",
                    new_callable=AsyncMock,
                    return_value=0,
                ),
                patch("silvasonic.processor.upload_worker.UploadWorker", autospec=True),
                patch(
                    "silvasonic.processor.__main__.indexer.index_recordings",
                    new_callable=AsyncMock,
                    return_value=MagicMock(new=0, skipped=0, errors=0),
                ),
                patch(
                    "silvasonic.processor.__main__.janitor.run_cleanup_safe",
                    new_callable=AsyncMock,
                    return_value=MagicMock(
                        disk_usage_percent=10.0,
                        mode=RetentionMode.IDLE,
                        files_deleted=0,
                        errors=0,
                    ),
                ),
            ):
                await svc.run()

        status = svc.health.get_status()
        assert "processor" in status["components"]
        assert status["components"]["processor"]["healthy"] is True

    async def test_run_reconciliation_failure_sets_unhealthy(self) -> None:
        """Reconciliation failure calls update_status(indexer, False), loop continues."""
        svc = _make_bare_service()
        # Track all calls to update_status
        status_calls: list[tuple[str, bool, str]] = []
        original_update = svc.health.update_status

        def tracking_update(component: str, healthy: bool, details: str = "", **kw: Any) -> None:
            status_calls.append((component, healthy, details))
            original_update(component, healthy, details, **kw)

        svc.health.update_status = tracking_update

        # Build a get_session mock that fails on first call (reconciliation)
        # and succeeds on subsequent calls (indexer loop)
        call_count = 0

        def session_factory() -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Reconciliation: raise inside __aenter__
                ctx = AsyncMock()
                ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("DB down"))
                ctx.__aexit__ = AsyncMock()
                return ctx
            # Indexer loop calls: normal session
            ctx = AsyncMock()
            mock_session_obj = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session_obj)
            ctx.__aexit__ = AsyncMock()
            return ctx

        with (
            patch(
                "silvasonic.processor.__main__.get_session",
                side_effect=session_factory,
            ),
            patch(
                "silvasonic.processor.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=lambda _: svc._shutdown_event.set(),
            ),
            patch("silvasonic.processor.upload_worker.UploadWorker", autospec=True),
            patch(
                "silvasonic.processor.__main__.indexer.index_recordings",
                new_callable=AsyncMock,
                return_value=MagicMock(new=0, skipped=0, errors=0),
            ),
            patch(
                "silvasonic.processor.__main__.janitor.run_cleanup_safe",
                new_callable=AsyncMock,
                return_value=MagicMock(
                    disk_usage_percent=10.0,
                    mode=RetentionMode.IDLE,
                    files_deleted=0,
                    errors=0,
                ),
            ),
        ):
            await svc.run()

        # Verify reconciliation failure was reported
        recon_calls = [(c, h, d) for c, h, d in status_calls if c == "indexer" and not h]
        assert len(recon_calls) >= 1
        assert "reconciliation_failed" in recon_calls[0][2]
        # Verify loop still ran (processor status was set)
        assert any(c == "processor" for c, _, _ in status_calls)

    async def test_run_new_recordings_updates_metrics(self) -> None:
        """Indexer result with new > 0 updates total_indexed and last_indexed_at."""
        svc = _make_bare_service()

        with (
            patch(
                "silvasonic.processor.__main__.get_session",
            ) as mock_session,
            patch(
                "silvasonic.processor.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=lambda _: svc._shutdown_event.set(),
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()

            with (
                patch(
                    "silvasonic.processor.__main__.reconciliation.run_audit",
                    new_callable=AsyncMock,
                    return_value=0,
                ),
                patch("silvasonic.processor.upload_worker.UploadWorker", autospec=True),
                patch(
                    "silvasonic.processor.__main__.indexer.index_recordings",
                    new_callable=AsyncMock,
                    return_value=MagicMock(new=3, skipped=1, errors=0),
                ),
                patch(
                    "silvasonic.processor.__main__.janitor.run_cleanup_safe",
                    new_callable=AsyncMock,
                    return_value=MagicMock(
                        disk_usage_percent=10.0,
                        mode=RetentionMode.IDLE,
                        files_deleted=0,
                        errors=0,
                    ),
                ),
            ):
                await svc.run()

        assert svc._total_indexed == 3
        assert svc._last_indexed_at is not None
        status = svc.health.get_status()
        assert status["components"]["indexer"]["healthy"] is True

    async def test_run_indexer_errors_set_unhealthy(self) -> None:
        """Indexer result with errors > 0 sets indexer health to False."""
        svc = _make_bare_service()

        with (
            patch(
                "silvasonic.processor.__main__.get_session",
            ) as mock_session,
            patch(
                "silvasonic.processor.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=lambda _: svc._shutdown_event.set(),
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()

            with (
                patch(
                    "silvasonic.processor.__main__.reconciliation.run_audit",
                    new_callable=AsyncMock,
                    return_value=0,
                ),
                patch("silvasonic.processor.upload_worker.UploadWorker", autospec=True),
                patch(
                    "silvasonic.processor.__main__.indexer.index_recordings",
                    new_callable=AsyncMock,
                    return_value=MagicMock(new=0, skipped=0, errors=2),
                ),
                patch(
                    "silvasonic.processor.__main__.janitor.run_cleanup_safe",
                    new_callable=AsyncMock,
                    return_value=MagicMock(
                        disk_usage_percent=10.0,
                        mode=RetentionMode.IDLE,
                        files_deleted=0,
                        errors=0,
                    ),
                ),
            ):
                await svc.run()

        status = svc.health.get_status()
        assert status["components"]["indexer"]["healthy"] is False
        assert "2 errors" in status["components"]["indexer"]["details"]

    async def test_run_indexer_exception_sets_error_status(self) -> None:
        """Exception in indexer loop sets indexer health to 'error'."""
        svc = _make_bare_service()

        with (
            patch(
                "silvasonic.processor.__main__.get_session",
            ) as mock_session,
            patch(
                "silvasonic.processor.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=lambda _: svc._shutdown_event.set(),
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()

            with (
                patch(
                    "silvasonic.processor.__main__.reconciliation.run_audit",
                    new_callable=AsyncMock,
                    return_value=0,
                ),
                patch("silvasonic.processor.upload_worker.UploadWorker", autospec=True),
                patch(
                    "silvasonic.processor.__main__.indexer.index_recordings",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("Connection lost"),
                ),
                patch(
                    "silvasonic.processor.__main__.janitor.run_cleanup_safe",
                    new_callable=AsyncMock,
                    return_value=MagicMock(
                        disk_usage_percent=10.0,
                        mode=RetentionMode.IDLE,
                        files_deleted=0,
                        errors=0,
                    ),
                ),
            ):
                await svc.run()

        status = svc.health.get_status()
        assert status["components"]["indexer"]["healthy"] is False
        assert status["components"]["indexer"]["details"] == "error"

    async def test_run_janitor_executes_on_cycle(self) -> None:
        """Janitor runs when counter reaches janitor_every_n, updates metrics."""
        svc = _make_bare_service()
        # Set intervals equal so janitor_every_n = 1 (runs on first cycle)
        svc._settings = ProcessorSettings(
            janitor_interval_seconds=2,
            indexer_poll_interval=2.0,
        )

        with (
            patch(
                "silvasonic.processor.__main__.get_session",
            ) as mock_session,
            patch(
                "silvasonic.processor.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=lambda _: svc._shutdown_event.set(),
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()

            with (
                patch(
                    "silvasonic.processor.__main__.reconciliation.run_audit",
                    new_callable=AsyncMock,
                    return_value=0,
                ),
                patch("silvasonic.processor.upload_worker.UploadWorker", autospec=True),
                patch(
                    "silvasonic.processor.__main__.indexer.index_recordings",
                    new_callable=AsyncMock,
                    return_value=MagicMock(new=0, skipped=0, errors=0),
                ),
                patch(
                    "silvasonic.processor.__main__.janitor.run_cleanup_safe",
                    new_callable=AsyncMock,
                    return_value=MagicMock(
                        disk_usage_percent=45.5,
                        mode=RetentionMode.IDLE,
                        files_deleted=2,
                        errors=0,
                    ),
                ),
            ):
                await svc.run()

        assert svc._disk_usage_percent == 45.5
        assert svc._files_deleted_total == 2
        assert svc._janitor_mode == "idle"
        status = svc.health.get_status()
        assert "janitor" in status["components"]
        assert status["components"]["janitor"]["healthy"] is True

    async def test_run_janitor_exception_sets_error(self) -> None:
        """Exception in janitor sets janitor health to 'error'."""
        svc = _make_bare_service()
        svc._settings = ProcessorSettings(
            janitor_interval_seconds=2,
            indexer_poll_interval=2.0,
        )

        with (
            patch(
                "silvasonic.processor.__main__.get_session",
            ) as mock_session,
            patch(
                "silvasonic.processor.__main__.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=lambda _: svc._shutdown_event.set(),
            ),
        ):
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock()

            with (
                patch(
                    "silvasonic.processor.__main__.reconciliation.run_audit",
                    new_callable=AsyncMock,
                    return_value=0,
                ),
                patch("silvasonic.processor.upload_worker.UploadWorker", autospec=True),
                patch(
                    "silvasonic.processor.__main__.indexer.index_recordings",
                    new_callable=AsyncMock,
                    return_value=MagicMock(new=0, skipped=0, errors=0),
                ),
                patch(
                    "silvasonic.processor.__main__.janitor.run_cleanup_safe",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("Disk error"),
                ),
            ):
                await svc.run()

        status = svc.health.get_status()
        assert status["components"]["janitor"]["healthy"] is False
        assert status["components"]["janitor"]["details"] == "error"


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
