#!/usr/bin/env python3
"""Run Ruff linter in read-only mode (no auto-fix).

Usage:
    python3 scripts/lint.py
"""

import subprocess
import sys
from pathlib import Path

from common import ensure_initialized, print_error, print_header, print_success

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    """Run ruff check in read-only mode."""
    ensure_initialized()
    print_header("Ruff Lint (Read-Only)")

    result = subprocess.run(["uv", "run", "ruff", "check", "."], cwd=PROJECT_ROOT)
    if result.returncode == 0:
        print_success("Ruff lint passed — no issues found.")
    else:
        print_error(f"Ruff lint found issues (exit {result.returncode}).")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
