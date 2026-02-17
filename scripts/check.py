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

# ── Project root = parent of scripts/ ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run(label: str, cmd: list[str]) -> bool:
    """Run a command, print a header, and return True on success."""
    print(f"\n{'=' * 60}")
    print(f"🔍 {label}")
    print(f"{'=' * 60}")
    print(f"   → {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode == 0:
        print(f"   ✅ {label} passed.")
    else:
        print(f"   ❌ {label} FAILED (exit {result.returncode}).", file=sys.stderr)
    return result.returncode == 0


def main() -> None:
    """Run ruff, mypy, and unit tests sequentially."""
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
    print(f"\n{'=' * 60}")
    print("📋 Summary")
    print(f"{'=' * 60}")
    all_ok = True
    for name, passed in results.items():
        icon = "✅" if passed else "❌"
        print(f"   {icon} {name}")
        if not passed:
            all_ok = False

    if all_ok:
        print("\n🎉 All checks passed!")
    else:
        print("\n💥 Some checks failed. Please fix the issues above.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
