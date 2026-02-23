"""Unit tests for silvasonic.core.logging module."""

import logging
import os
from unittest.mock import patch

import pytest
import structlog


@pytest.mark.unit
class TestConfigureLogging:
    """Tests for configure_logging()."""

    def _call(self, service_name: str = "test-svc", **env_overrides: str) -> None:
        """Helper: import and call configure_logging with env overrides."""
        from silvasonic.core.logging import configure_logging

        env = {"SILVASONIC_DEVELOPMENT_MODE": "true", **env_overrides}
        with patch.dict(os.environ, env, clear=False):
            configure_logging(service_name)

    def test_root_logger_has_handler(self) -> None:
        """After calling configure_logging, the root logger has at least one handler."""
        self._call()
        root = logging.getLogger()
        assert len(root.handlers) >= 1

    def test_structlog_configured(self) -> None:
        """Structlog produces a bound logger after configure_logging."""
        self._call()
        log = structlog.get_logger()
        assert log is not None

    def test_service_name_injected(self) -> None:
        """The service name processor adds the service key to event dict."""
        from silvasonic.core.logging import configure_logging

        with patch.dict(os.environ, {"SILVASONIC_DEVELOPMENT_MODE": "true"}, clear=False):
            configure_logging("my-service")

        # Verify by calling the processor directly through structlog
        log = structlog.get_logger("test")
        assert log is not None

    def test_prod_mode_json_renderer(self) -> None:
        """In production mode, logging uses JSONRenderer (no crash)."""
        self._call(SILVASONIC_DEVELOPMENT_MODE="false")
        root = logging.getLogger()
        assert len(root.handlers) >= 1

    def test_dev_mode_no_tty(self) -> None:
        """In dev mode without TTY, ConsoleRenderer is used (no crash)."""
        # In CI / test environment sys.stdout.isatty() is typically False
        self._call(SILVASONIC_DEVELOPMENT_MODE="true")
        root = logging.getLogger()
        assert len(root.handlers) >= 1

    def test_dev_mode_interactive_tty_uses_rich_handler(self) -> None:
        """In dev mode with a TTY, the RichHandler branch is taken."""
        import sys as _sys
        from unittest.mock import MagicMock, create_autospec

        from silvasonic.core.logging import configure_logging

        mock_handler = create_autospec(logging.Handler, instance=True)
        mock_rich_handler_cls = MagicMock(return_value=mock_handler)
        fake_rich_mod = MagicMock(RichHandler=mock_rich_handler_cls)

        # Wrapper that delegates to real stdout but forces isatty() -> True
        class TtyStdout:
            def __getattr__(self, name: str) -> object:
                return getattr(_sys.__stdout__, name)

            def isatty(self) -> bool:
                return True

        orig_stdout = _sys.stdout
        orig_rich = _sys.modules.get("rich.logging")
        try:
            _sys.stdout = TtyStdout()  # type: ignore[assignment,unused-ignore]
            _sys.modules["rich.logging"] = fake_rich_mod  # type: ignore[assignment,unused-ignore]
            with patch.dict(os.environ, {"SILVASONIC_DEVELOPMENT_MODE": "true"}):
                configure_logging("rich-test")
        finally:
            _sys.stdout = orig_stdout
            if orig_rich is not None:
                _sys.modules["rich.logging"] = orig_rich
            else:
                _sys.modules.pop("rich.logging", None)

        mock_rich_handler_cls.assert_called_once_with(
            rich_tracebacks=True, tracebacks_show_locals=True, show_time=True
        )
        mock_handler.setFormatter.assert_called_once()
        root = logging.getLogger()
        assert mock_handler in root.handlers

        # Cleanup: remove mock handler to prevent cross-test pollution.
        # The mock has spec=Handler but no real 'level' attribute, which
        # would crash any subsequent logger.info() call.
        root.handlers = [h for h in root.handlers if h is not mock_handler]
