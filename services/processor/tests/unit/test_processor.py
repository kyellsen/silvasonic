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
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.config_schemas import ProcessorSettings
from silvasonic.core.health import HealthMonitor
from silvasonic.processor.__main__ import ProcessorService


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
    return svc


# ---------------------------------------------------------------------------
# Package import
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestProcessorPackage:
    """Basic package-level tests."""

    def test_package_importable(self) -> None:
        """Processor package is importable."""
        import silvasonic.processor

        assert silvasonic.processor is not None

    def test_version_exported(self) -> None:
        """__version__ is exported from the processor package."""
        from silvasonic.processor import __version__

        assert isinstance(__version__, str)
        assert len(__version__) > 0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestProcessorConfig:
    """Tests for service-level configuration."""

    def test_service_name(self) -> None:
        """service_name is 'processor'."""
        assert ProcessorService.service_name == "processor"

    def test_service_port_default(self) -> None:
        """service_port defaults to 9200."""
        assert ProcessorService.service_port == 9200

    def test_service_port_env_override(self) -> None:
        """service_port respects SILVASONIC_PROCESSOR_PORT at instantiation."""
        svc = _make_bare_service()
        # Simulate __init__ reading env var
        with patch.dict("os.environ", {"SILVASONIC_PROCESSOR_PORT": "7777"}):
            from silvasonic.processor.settings import ProcessorEnvSettings

            cfg = ProcessorEnvSettings()
            svc.service_port = cfg.PROCESSOR_PORT
        assert svc.service_port == 7777


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

        with patch(
            "silvasonic.processor.__main__.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=lambda _: svc._shutdown_event.set(),
        ):
            await svc.run()

        status = svc.health.get_status()
        assert "processor" in status["components"]
        assert status["components"]["processor"]["healthy"] is True


# ---------------------------------------------------------------------------
# get_extra_meta
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestProcessorGetExtraMeta:
    """Tests for the get_extra_meta() override."""

    def test_extra_meta_empty_phase1(self) -> None:
        """get_extra_meta() returns empty dict in Phase 1 (placeholder)."""
        svc = _make_bare_service()
        meta = svc.get_extra_meta()
        assert meta == {}


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
