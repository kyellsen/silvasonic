#!/usr/bin/env python3
"""Light cleanup: remove junk from the project root and purge caches.

Only entries NOT listed in the `.keep` whitelist are deleted.
Does NOT touch container volumes or .venv (use `make clean` / `make nuke`).

Usage:
    python scripts/clear.py              # normal run
    python scripts/clear.py --dry-run    # preview only, nothing is deleted
"""

import shutil
import sys
from pathlib import Path

from common import print_header, print_step, print_success, print_warning

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEEP_FILE = PROJECT_ROOT / ".keep"

# Directories to remove recursively (project-wide)
CACHE_DIRS = [
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


def clear_root(dry_run: bool = False) -> None:
    """Delete every root-level entry that is NOT in the .keep whitelist."""
    keep = load_keep_entries()
    if not keep:
        return

    removed: list[str] = []
    for entry in sorted(PROJECT_ROOT.iterdir()):
        name = entry.name
        if name in keep:
            continue

        # Safety: never touch .git even if someone forgets to list it
        if name == ".git":
            continue

        if dry_run:
            kind = "dir" if entry.is_dir() else "file"
            print_warning(f"[DRY-RUN] Would delete {kind}: {name}")
            removed.append(name)
            continue

        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            removed.append(name)
        except OSError as exc:
            print_warning(f"Could not remove {name}: {exc}")

    prefix = "[DRY-RUN] " if dry_run else ""
    if removed:
        print_success(f"{prefix}Removed {len(removed)} root entries: {', '.join(removed)}")
    else:
        print_success("Root is already clean.")


def remove_cache_dirs(dry_run: bool = False) -> None:
    """Walk the project tree and remove known cache directories."""
    for pattern in CACHE_DIRS:
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


def main() -> None:
    """Run the light cleanup pipeline."""
    dry_run = "--dry-run" in sys.argv

    print_header("Clear - Light Cleanup" + (" (DRY-RUN)" if dry_run else ""))

    print_step("Cleaning project root (respecting .keep)...")
    clear_root(dry_run=dry_run)

    print_step("Removing caches and build artifacts...")
    remove_cache_dirs(dry_run=dry_run)

    print_success("Clear complete.")


if __name__ == "__main__":
    main()
