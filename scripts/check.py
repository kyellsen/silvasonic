"""Fast static analysis and unit-test check.

Usage:
    python3 scripts/check.py

Runs (in order):
    1. uv lock --check - lock-file consistency
    2. ruff check      - lint (no autofix)
    3. mypy            - static type checking (strict, incl. services + packages)
    4. pytest -m unit  - fast isolated tests
"""

import subprocess
import sys
from pathlib import Path

from common import (
    Colors,
    ensure_initialized,
    print_error,
    print_header,
    print_step,
    print_success,
)
from test import cmd_unit

# ── Project root = parent of scripts/ ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Stages that may fail without aborting the pipeline.
# Their result is still shown in the summary and affects the exit code.
NON_CRITICAL_STAGES: set[str] = {"Lock-File Check"}


def _run(label: str, cmd: list[str]) -> bool:
    """Run a command, print a header, and return True on success."""
    print_header(label)
    print_step(f"{' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode == 0:
        print_success(f"{label} passed.")
    else:
        print_error(f"{label} FAILED (exit {result.returncode}).")
    return result.returncode == 0


def main() -> dict[str, bool | None]:
    """Run lock-check, ruff, mypy, and unit tests sequentially.

    Non-critical stages (Lock-File Check) may fail without aborting
    the pipeline.  Critical stages abort on first failure.

    Returns a dict of {check_name: passed/failed/skipped} for use by check_all.py.
    """
    ensure_initialized()

    all_stages: list[tuple[str, list[str]]] = [
        ("Lock-File Check", ["uv", "lock", "--check"]),
        ("Ruff Lint", ["uv", "run", "ruff", "check", "."]),
        ("Mypy", ["uv", "run", "mypy", "."]),
        ("Unit Tests", cmd_unit()),
    ]

    results: dict[str, bool | None] = {}

    # ── Early-fail for critical stages; non-critical stages continue ──────
    for i, (label, cmd) in enumerate(all_stages):
        passed = _run(label, cmd)
        results[label] = passed
        if not passed and label not in NON_CRITICAL_STAGES:
            # Mark remaining stages as skipped
            for skip_label, _ in all_stages[i + 1 :]:
                results[skip_label] = None
            break

    # ── Summary ───────────────────────────────────────────────────────────────
    print_header("Summary")
    all_ok = True
    for name, result in results.items():
        if result is None:
            print(f"   {Colors.WARNING}⏭️  {name} (skipped){Colors.ENDC}")
        elif result:
            print(f"   {Colors.OKGREEN}✅ {name}{Colors.ENDC}")
        else:
            print(f"   {Colors.FAIL}❌ {name}{Colors.ENDC}")
            all_ok = False

    if all_ok and all(v is not None for v in results.values()):
        print(f"\n{Colors.OKGREEN}{Colors.BOLD}🎉 All checks passed!{Colors.ENDC}")
    else:
        print_error("Some checks failed. Please fix the issues above.")
        sys.exit(1)

    return results


if __name__ == "__main__":
    main()
