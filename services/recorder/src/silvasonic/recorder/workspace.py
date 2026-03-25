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


def ensure_workspace(base: Path) -> None:
    """Create the full workspace directory structure.

    Idempotent — safe to call on every startup.  Creates all directories
    needed for both Raw and Processed streams (``data/`` and ``.buffer/``).

    Also cleans up any orphan ``.wav`` files left in ``.buffer/`` from
    a previous crash (segments that were never promoted).

    Args:
        base: Workspace root path (e.g. ``/app/workspace``).
    """
    for subdir in _WORKSPACE_DIRS:
        path = base / subdir
        path.mkdir(parents=True, exist_ok=True)

    # Clean up orphan segments from previous recording sessions.
    # These are WAV files left in .buffer/ after an unclean shutdown
    # (e.g. power loss, OOM kill) where the SegmentPromoter never
    # got a chance to promote them.  We promote them now so the
    # Indexer can pick them up.
    orphans_promoted = 0
    for stream in ("raw", "processed"):
        buffer_dir = base / ".buffer" / stream
        data_dir = base / "data" / stream
        for wav in sorted(buffer_dir.glob("*.wav")):
            dst = data_dir / wav.name
            with contextlib.suppress(OSError):
                wav.rename(dst)
                orphans_promoted += 1

    log.info(
        "workspace.ensured",
        base=str(base),
        dirs=len(_WORKSPACE_DIRS),
        orphans_promoted=orphans_promoted,
    )
