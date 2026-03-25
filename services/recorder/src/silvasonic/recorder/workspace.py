"""Workspace directory management for the Recorder service.

Creates and maintains the standardized workspace directory structure
required by the Dual Stream Architecture (ADR-0011, ADR-0024).
"""

import contextlib
from pathlib import Path

import structlog

log = structlog.get_logger()

# Subdirectories that MUST exist before recording starts.
# .buffer/ holds in-progress segments; data/ holds promoted (complete) files.
_WORKSPACE_DIRS = [
    "data/raw",
    "data/processed",
    ".buffer/raw",
    ".buffer/processed",
]

# Stale segment-list CSVs from previous runs (ADR-0024)
_STALE_FILES = [
    ".buffer/raw_segments.csv",
    ".buffer/processed_segments.csv",
]


def ensure_workspace(base: Path) -> None:
    """Create the full workspace directory structure.

    Idempotent — safe to call on every startup.  Creates all directories
    needed for both Raw and Processed streams (``data/`` and ``.buffer/``).
    Also cleans up stale segment-list CSVs from previous runs.

    Args:
        base: Workspace root path (e.g. ``/app/workspace``).
    """
    for subdir in _WORKSPACE_DIRS:
        path = base / subdir
        path.mkdir(parents=True, exist_ok=True)

    # Clean up stale segment-list CSVs from previous recording sessions
    cleaned = 0
    for stale in _STALE_FILES:
        path = base / stale
        with contextlib.suppress(OSError):
            if path.exists():
                path.unlink()
                cleaned += 1

    log.info("workspace.ensured", base=str(base), dirs=len(_WORKSPACE_DIRS), cleaned=cleaned)
