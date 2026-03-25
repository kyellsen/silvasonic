"""Workspace directory management for the Recorder service.

Creates and maintains the standardized workspace directory structure
required by the Dual Stream Architecture (ADR-0011, ADR-0009).
"""

from pathlib import Path

import structlog

log = structlog.get_logger()

# Subdirectories that MUST exist before recording starts.
# Phase 1 uses only data/raw/ and .buffer/raw/.
# Phase 4 (Dual Stream) will additionally use data/processed/ and .buffer/processed/.
_WORKSPACE_DIRS = [
    "data/raw",
    "data/processed",
    ".buffer/raw",
    ".buffer/processed",
]


def ensure_workspace(base: Path) -> None:
    """Create the full workspace directory structure.

    Idempotent — safe to call on every startup.  Creates all directories
    needed for both Raw and Processed streams (``data/`` and ``.buffer/``).

    Args:
        base: Workspace root path (e.g. ``/app/workspace``).
    """
    for subdir in _WORKSPACE_DIRS:
        path = base / subdir
        path.mkdir(parents=True, exist_ok=True)

    log.info("workspace.ensured", base=str(base), dirs=len(_WORKSPACE_DIRS))
