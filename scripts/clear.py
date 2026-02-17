#!/usr/bin/env python3
"""Light cleanup: quarantine junk from the project root and purge caches.

Entries NOT listed in the `.keep` whitelist are handled as follows:
- Known junk (caches, logs, tmp files) → deleted immediately
- Unknown entries → moved to `.trash/` for safe recovery

Does NOT touch container volumes or .venv (use `just clean` / `just nuke`).

Usage:
    python scripts/clear.py              # normal run
    python scripts/clear.py --dry-run    # preview only, nothing is moved
"""

import shutil
import sys
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path

from common import print_header, print_step, print_success, print_warning

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEEP_FILE = PROJECT_ROOT / ".keep"
TRASH_DIR = PROJECT_ROOT / ".trash"

# Root-level directories that are ALWAYS deleted (never quarantined)
AUTO_DELETE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    ".tox",
    ".nox",
    "htmlcov",
    ".eggs",
    "build",
    "dist",
}

# Glob patterns for root-level files that are ALWAYS deleted (never quarantined)
AUTO_DELETE_PATTERNS = [
    "*.log",
    "*.log.*",
    "*.tmp",
    "*.bak",
    "*.swp",
    "*.swo",
    "*_output.*",
    "*_output_*",
    "*_debug*",
    "tmp_*",
    "temp_*",
    "test_out_*",
]

# Same directories, but searched recursively project-wide for cache cleanup
RECURSIVE_CACHE_DIRS = [
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
]


def load_keep_entries() -> set[str]:
    """Read .keep and return a set of protected basenames (without trailing /)."""
    if not KEEP_FILE.exists():
        print_warning(f"{KEEP_FILE} not found - skipping root cleanup!")
        return set()

    entries: set[str] = set()
    for line in KEEP_FILE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Normalise: remove trailing slash so both "docs/" and "docs" match
        entries.add(stripped.rstrip("/"))
    return entries


def _is_auto_delete(name: str, is_dir: bool) -> bool:
    """Check if a root-level entry matches known junk patterns."""
    if is_dir and name in AUTO_DELETE_DIRS:
        return True
    if not is_dir:
        for pattern in AUTO_DELETE_PATTERNS:
            if fnmatch(name, pattern):
                return True
    return False


def quarantine_root(dry_run: bool = False) -> None:
    """Clean root: auto-delete known junk, quarantine unknown entries."""
    keep = load_keep_entries()
    if not keep:
        return

    deleted: list[str] = []
    trashed: list[str] = []
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")

    for entry in sorted(PROJECT_ROOT.iterdir()):
        name = entry.name
        if name in keep:
            continue

        # Safety: never touch .git even if someone forgets to list it
        if name == ".git":
            continue

        is_dir = entry.is_dir()

        # --- Known junk → delete immediately ---
        if _is_auto_delete(name, is_dir):
            if dry_run:
                kind = "dir" if is_dir else "file"
                print_warning(f"[DRY-RUN] Would delete {kind}: {name}")
            else:
                try:
                    if is_dir:
                        shutil.rmtree(entry)
                    else:
                        entry.unlink()
                except OSError as exc:
                    print_warning(f"Could not delete {name}: {exc}")
            deleted.append(name)
            continue

        # --- Unknown entry → quarantine to .trash/ ---
        if dry_run:
            kind = "dir" if is_dir else "file"
            print_warning(f"[DRY-RUN] Would trash {kind}: {name}")
            trashed.append(name)
            continue

        try:
            TRASH_DIR.mkdir(exist_ok=True)
            dest = TRASH_DIR / f"{name}__{timestamp}"
            shutil.move(str(entry), str(dest))
            trashed.append(name)
        except OSError as exc:
            print_warning(f"Could not trash {name}: {exc}")

    prefix = "[DRY-RUN] " if dry_run else ""
    if deleted:
        print_success(f"{prefix}Deleted {len(deleted)} junk entries: {', '.join(deleted)}")
    if trashed:
        print_success(
            f"{prefix}Moved {len(trashed)} unknown entries to .trash/: {', '.join(trashed)}"
        )
    if not deleted and not trashed:
        print_success("Root is already clean.")


def remove_cache_dirs(dry_run: bool = False) -> None:
    """Walk the project tree and remove known cache directories."""
    for pattern in RECURSIVE_CACHE_DIRS:
        found = list(PROJECT_ROOT.rglob(pattern))
        for d in found:
            if d.is_dir():
                if dry_run:
                    print_warning(f"[DRY-RUN] Would delete cache: {d.relative_to(PROJECT_ROOT)}")
                else:
                    shutil.rmtree(d, ignore_errors=True)
        if found:
            prefix = "[DRY-RUN] " if dry_run else ""
            print_success(f"{prefix}Removed {len(found)}x {pattern}")


def empty_trash(dry_run: bool = False) -> None:
    """Remove all contents of the .trash/ directory."""
    if not TRASH_DIR.exists():
        return

    items = list(TRASH_DIR.iterdir())
    if not items:
        return

    if dry_run:
        print_warning(f"[DRY-RUN] Would empty .trash/ ({len(items)} items)")
        return

    shutil.rmtree(TRASH_DIR, ignore_errors=True)
    print_success(f"Emptied .trash/ ({len(items)} items)")


def main(dry_run: bool | None = None) -> None:
    """Run the light cleanup pipeline.

    Args:
        dry_run: If None, reads --dry-run from sys.argv (CLI mode).
                 If explicit bool, uses that value (API mode).
    """
    if dry_run is None:
        dry_run = "--dry-run" in sys.argv

    print_header("Clear - Light Cleanup" + (" (DRY-RUN)" if dry_run else ""))

    print_step("Cleaning project root (respecting .keep)...")
    quarantine_root(dry_run=dry_run)

    print_step("Removing caches and build artifacts...")
    remove_cache_dirs(dry_run=dry_run)

    print_success("Clear complete.")


if __name__ == "__main__":
    main()
