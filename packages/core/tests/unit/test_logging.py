import logging
import sys
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
import structlog
from silvasonic.core.logging import configure_logging


@pytest.fixture
def mock_structlog_configure() -> Generator[MagicMock, None, None]:
    """Mock structlog.configure for isolation."""
    with patch("structlog.configure") as mock:
        yield mock


@pytest.fixture
def mock_logging() -> Generator[tuple[MagicMock, MagicMock, MagicMock, MagicMock], None, None]:
    """Mock standard logging module components."""
    with (
        patch("logging.getLogger") as mock_get_logger,
        patch("logging.StreamHandler") as mock_stream_handler,
        patch("logging.handlers.RotatingFileHandler") as mock_file_handler,
    ):
        root_logger = MagicMock()
        mock_get_logger.return_value = root_logger
        yield mock_get_logger, root_logger, mock_stream_handler, mock_file_handler


def test_configure_logging_stdout_only(
    mock_logging: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mock_structlog_configure: MagicMock,
) -> None:
    """Test logging configuration when only stdout is enabled."""
    mock_get_logger, root_logger, mock_stream_handler, _ = mock_logging

    configure_logging(service_name="test_service", log_dir=None)

    # Check stdout handler configuration
    mock_stream_handler.assert_called_with(sys.stdout)
    assert root_logger.addHandler.called
    # Ensure generated handler was added
    handler_instance = mock_stream_handler.return_value
    handler_instance.setLevel.assert_called_with(logging.INFO)
    assert isinstance(
        handler_instance.setFormatter.call_args[0][0], structlog.stdlib.ProcessorFormatter
    )


def test_configure_logging_with_file(
    mock_logging: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mock_structlog_configure: MagicMock,
) -> None:
    """Test logging configuration with file output enabled."""
    mock_get_logger, root_logger, _, mock_file_handler = mock_logging

    with patch("os.makedirs") as mock_makedirs:
        configure_logging(service_name="test_service", log_dir="/tmp/logs")

        mock_makedirs.assert_called_with("/tmp/logs", exist_ok=True)
        mock_file_handler.assert_called_with(
            "/tmp/logs/test_service.log", maxBytes=10 * 1024 * 1024, backupCount=5
        )

        # Ensure file handler added to root logger
        handler_instance = mock_file_handler.return_value
        handler_instance.setLevel.assert_called_with(logging.INFO)
        root_logger.addHandler.assert_any_call(handler_instance)


def test_configure_logging_file_error(
    mock_logging: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test graceful handling of file logging configuration errors."""
    mock_get_logger, root_logger, _, _ = mock_logging

    # Simulate file permission error
    with patch("os.makedirs", side_effect=PermissionError("Testing Error")):
        configure_logging(service_name="test_service", log_dir="/root/protected")

        # Verify it didn't crash and printed to stderr
        captured = capsys.readouterr()
        assert "FAILED TO SETUP FILE LOGGING" in captured.err


def test_structlog_configuration(
    mock_logging: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mock_structlog_configure: MagicMock,
) -> None:
    """Verify structlog is configured with correct parameters."""
    configure_logging(service_name="test_service")

    mock_structlog_configure.assert_called_once()
    kwargs = mock_structlog_configure.call_args[1]
    assert kwargs["logger_factory"].__class__ == structlog.stdlib.LoggerFactory
    assert kwargs["wrapper_class"] == structlog.stdlib.BoundLogger
