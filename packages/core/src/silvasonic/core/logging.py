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
    log_format = os.environ.get("SILVASONIC_LOG_FORMAT", "dev").lower()
    is_json = log_format == "json"

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
    if is_json:
        # PROD: JSON array tracebacks (perfect for Loki/Elasticsearch)
        shared_processors.append(structlog.processors.dict_tracebacks)
        renderer = structlog.processors.JSONRenderer()
    else:
        # DEV: Beautiful, colored, multiline tracebacks for humans
        shared_processors.append(structlog.processors.format_exc_info)
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
