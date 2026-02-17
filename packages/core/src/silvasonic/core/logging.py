import logging
import os
import sys
from typing import Any

import structlog


def configure_logging(service_name: str) -> None:
    """Configures modern, container-first structured logging for Silvasonic.

    Logs are strictly emitted to STDOUT. The container runtime (Podman/Docker)
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

    # 4. Environment-Specific Rendering
    renderer: Any
    if not dev_mode:
        # PROD: JSON array tracebacks (perfect for Loki/Elasticsearch)
        shared_processors.append(structlog.processors.dict_tracebacks)
        renderer = structlog.processors.JSONRenderer()
    else:
        # DEV: Beautiful, colored, multiline tracebacks for humans via Rich
        from rich.logging import RichHandler

        # Rich handles timestamps and levels beautifully; we simplify the structlog pipeline
        # to avoid double-printing or formatting conflicts.
        renderer = structlog.dev.ConsoleRenderer(colors=True)

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

    if dev_mode:
        # Import inside function to avoid heavy dependency at module level if not needed
        from rich.logging import RichHandler

        # RichHandler inherently handles timestamp, level coloring, and formatting.
        # We perform a minimal setup here.
        rich_handler = RichHandler(
            rich_tracebacks=True, tracebacks_show_locals=True, show_time=True
        )
        # Note: We bind the ProcessorFormatter to the handler so structlog-processed messages
        # still pass through (rendering as the 'message' string).
        # However, for pure stdlib logs, Rich does its own magic.
        # The key is that `renderer` above (ConsoleRenderer) returns a string.
        # RichHandler expects a string message.
        rich_handler.setFormatter(formatter)
        root_logger.addHandler(rich_handler)
    else:
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
