import logging
import os
import sys
from typing import Any

import structlog


def _shorten_timestamp(
    _logger: logging.Logger, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Truncate ISO timestamp to second precision for human readability.

    ``2026-03-29T10:01:58.119872Z`` → ``10:01:58``

    Only applied in dev mode; production JSON keeps full precision.
    """
    ts = event_dict.get("timestamp", "")
    if isinstance(ts, str) and "T" in ts:
        # Extract HH:MM:SS from ISO format, drop date + sub-seconds
        time_part = ts.split("T", 1)[1]
        event_dict["timestamp"] = time_part.split(".")[0].rstrip("Z")
    return event_dict


def _shorten_logger_name(
    _logger: logging.Logger, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Shorten logger name to its last dotted component.

    ``silvasonic.controller.seeder`` → ``seeder``

    The event name already carries semantic context (e.g. ``seeder.profiles.inserted``),
    so the full module path is redundant in dev console output.
    """
    name = event_dict.get("logger_name", "")
    if isinstance(name, str) and "." in name:
        event_dict["logger_name"] = name.rsplit(".", 1)[-1]
    return event_dict


def configure_logging(service_name: str) -> None:
    """Configures modern, container-first structured logging for Silvasonic.

    Logs are strictly emitted to STDOUT. The container runtime (Podman)
    is responsible for capturing, rotating, and persisting these logs.

    Args:
        service_name: Name of the service (e.g., 'recorder', 'controller')
    """
    # 1. Evaluate Environment
    dev_mode = os.environ.get("SILVASONIC_DEVELOPMENT_MODE", "True").lower() in (
        "true",
        "1",
        "yes",
    )

    # 2. Inject Context (Service Name)
    def add_service_name(
        logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        event_dict["service"] = service_name
        return event_dict

    # 3. Core Processors (Applied to both Structlog AND Standard Library logs)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        add_service_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    # Dev-only: human-friendly timestamp + short logger name
    if dev_mode:
        shared_processors.append(_shorten_timestamp)
        shared_processors.append(_shorten_logger_name)

    # 4. Environment-Specific Rendering
    #
    # Three modes:
    #   - PROD (!dev_mode): JSON lines — ideal for Loki / Elasticsearch
    #   - DEV + TTY: Rich console — beautiful colors and tracebacks
    #   - DEV + no TTY (container): structlog ConsoleRenderer — safe, no hang
    #
    # RichHandler hangs in containers without a TTY because Rich's Console
    # tries to detect terminal capabilities.  We detect this at runtime.

    is_interactive = sys.stdout.isatty()
    renderer: Any

    if not dev_mode:
        # PROD: JSON array tracebacks (perfect for Loki/Elasticsearch)
        shared_processors.append(structlog.processors.dict_tracebacks)
        renderer = structlog.processors.JSONRenderer()
    else:
        # DEV: Colored console output (works with and without TTY)
        renderer = structlog.dev.ConsoleRenderer(
            colors=is_interactive,
            pad_event_to=40,
        )

    # 5. Bridge: Standard Library -> Structlog Format
    # `foreign_pre_chain` ensures third-party logs get timestamps and service names
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # 6. Configure Standard Library Root Logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()  # Wipe any existing handlers

    if dev_mode and is_interactive:
        # Interactive terminal: use RichHandler for beautiful output (dev-only dep)
        try:
            from rich.logging import RichHandler

            rich_handler = RichHandler(
                rich_tracebacks=True, tracebacks_show_locals=True, show_time=True
            )
            rich_handler.setFormatter(formatter)
            root_logger.addHandler(rich_handler)
        except ImportError:
            # rich not installed (production container) — fall back to plain handler
            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setFormatter(formatter)
            root_logger.addHandler(stdout_handler)
    else:
        # Container / CI / prod: plain StreamHandler to stdout (never blocks)
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)
        root_logger.addHandler(stdout_handler)

    # 7. Finalize Structlog Configuration
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
