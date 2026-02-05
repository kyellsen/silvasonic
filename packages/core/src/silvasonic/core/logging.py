import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any

import structlog


def configure_logging(service_name: str, log_dir: str | None = None) -> None:
    """Configure structured logging for Silvasonic Services.

    Dual-Logging Strategy:
    1. STDOUT: JSON formatted for Podman/UI (Always enabled)
    2. FILE: Rotating log file (Enabled if log_dir is provided)

    Args:
        service_name: Name of the service (e.g., 'recorder', 'controller')
        log_dir: Path to directory where logs should be stored (e.g., '/var/log/silvasonic')
    """
    # Shared Processors
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # 1. Console Handler (Stdout) - JSON for machine parsing/UI streaming
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    # Use JSON renderer for stdout so Status Board can parse it easily
    # Or should we use ConsoleRenderer for readability?
    # Guidance says: "Real-time: Logs are printed to stdout (JSON) for Podman and the Status Board."
    # So we need a formatter that outputs JSON.
    # But structlog.stdlib.LoggerFactory delegates to standard lib handlers.
    # We need to render to string before passing to handler, OR use structlog's wrap_logger.
    # Best practice with structlog+stdlib is to let structlog do the formatting.

    # Actually, simpler approach:
    # Use structlog.configure to output to standard lib logging,
    # and configure standard lib logging to have multiple handlers.

    # However, standard lib formatter is dumb.
    # Better approach: Use structlog.PrintLogger? No, we need file output.

    # Standard Pattern for Dual Output with Structlog:
    # Configure structlog to format the event dict, then pass to a "processor" that
    # distributes to files and stdout.
    # But usually it's easier to just rely on standard logging for distribution.

    # Let's use structlog to format as JSON, then print to stdout.
    # AND optionally open a file and print there too.
    # But files usually need key=value or human readable, while machines want JSON.

    # Let's stick to the plan:
    # Stdout -> JSON (for UI)
    # File -> Human Readable (for debugging) or JSON?
    # Plan says: "RotatingFileHandler -> {log_dir}/{service_name}.log"

    # Let's configure ROOT logger of stdlib.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = []  # Clear existing

    # Determine log format from environment (default: json)
    # Options: 'json', 'dev', 'human'
    log_format = os.environ.get("SILVASONIC_LOG_FORMAT", "json").lower()
    renderer: Any

    if log_format in ("dev", "human"):
        # Use ConsoleRenderer for human-readable logs
        # Note: This might emit ANSI colors which could look raw in web UIs that don't support Xterm.js
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        # Default to JSON for machine parsing (Podman, Status Board, etc.)
        renderer = structlog.processors.JSONRenderer()

    # 1. Stdout
    # Let's use structlog.stdlib.ProcessorFormatter, it is the modern way.
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(structlog.stdlib.ProcessorFormatter(processor=renderer))
    root_logger.addHandler(ch)

    # 2. File: Human Readable (if dir exists/provided)
    if log_dir:
        try:
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            log_file = log_path / f"{service_name}.log"

            fh = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,  # 10MB x 5
            )
            fh.setLevel(logging.INFO)
            # Use the same renderer for file consistency
            fh.setFormatter(structlog.stdlib.ProcessorFormatter(processor=renderer))
            root_logger.addHandler(fh)
        except Exception as e:
            # Fallback if file IO fails
            print(f"FAILED TO SETUP FILE LOGGING: {e}", file=sys.stderr)

    # Configure Structlog to wrap stdlib
    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
