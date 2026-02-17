"""Full static analysis and unit-test check.

Usage:
    uv run python scripts/check.py

Runs (in order):
    1. ruff check   - lint (no autofix)
    2. mypy         - static type checking
    3. pytest -m unit - fast isolated tests
"""

import subprocess
import sys
from pathlib import Path

from common import Colors, print_error, print_header, print_step, print_success

# ── Project root = parent of scripts/ ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def main() -> dict[str, bool]:
    """Run ruff, mypy, and unit tests sequentially.

    Returns a dict of {check_name: passed} for use by check_full.py.
    """
    results: dict[str, bool] = {}

    # 1. Ruff lint (strict, no autofix)
    results["Ruff Lint"] = _run("Ruff Lint", ["uv", "run", "ruff", "check", "."])

    # 2. Mypy static type check
    results["Mypy"] = _run("Mypy", ["uv", "run", "mypy", "."])

    # 3. Unit tests
    results["Unit Tests"] = _run(
        "Unit Tests", ["uv", "run", "pytest", "-m", "unit", "--tb=short", "-q"]
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    print_header("Summary")
    all_ok = True
    for name, passed in results.items():
        if passed:
            print(f"   {Colors.OKGREEN}✅ {name}{Colors.ENDC}")
        else:
            print(f"   {Colors.FAIL}❌ {name}{Colors.ENDC}")
            all_ok = False

    if all_ok:
        print(f"\n{Colors.OKGREEN}{Colors.BOLD}🎉 All checks passed!{Colors.ENDC}")
    else:
        print_error("Some checks failed. Please fix the issues above.")
        sys.exit(1)

    return results


if __name__ == "__main__":
    main()
