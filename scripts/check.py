"""Fast static analysis and unit-test check.

Usage:
    python3 scripts/check.py

Runs (in order):
    1. uv lock --check - lock-file consistency
    2. ruff check      - lint (no autofix)
    3. mypy            - static type checking (strict, incl. services + packages)
    4. pytest -m unit  - fast isolated tests

Ruff and Mypy always both run so the developer gets full lint+type
feedback in a single pass.  If either fails the pipeline aborts
before moving on to the test stages.
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

# Stages that always run even if a sibling fails.
# After all ALWAYS_RUN stages have executed, the pipeline aborts if
# any of them failed.
ALWAYS_RUN_STAGES: set[str] = {"Ruff Lint", "Mypy"}


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

    Returns a dict of {check_name: passed/failed/skipped} for use by ci.py.
    """
    ensure_initialized()

    is_verify = "--verify" in sys.argv
    targets: list[str] = [arg for arg in sys.argv[1:] if arg != "--verify"]
    if not targets:
        targets = ["."]

    all_stages: list[tuple[str, list[str]]] = [
        ("Lock-File Check", ["uv", "lock", "--check"]),
        ("Ruff Lint", ["uv", "run", "ruff", "check", *targets]),
        ("Mypy", ["uv", "run", "mypy", *targets]),
        ("Unit Tests", cmd_unit()),
    ]

    if is_verify:
        from test import cmd_integration

        all_stages.append(("Integration Tests", cmd_integration()))

    results: dict[str, bool | None] = {}

    # ── Run stages with always-run group support ─────────────────────────
    always_run_failed = False
    for i, (label, cmd) in enumerate(all_stages):
        passed = _run(label, cmd)
        results[label] = passed

        if not passed:
            if label in ALWAYS_RUN_STAGES:
                # Record failure but keep going so sibling stages run.
                always_run_failed = True
            elif label not in NON_CRITICAL_STAGES:
                # Hard abort for other critical stages.
                for skip_label, _ in all_stages[i + 1 :]:
                    results[skip_label] = None
                break

        # After leaving the always-run group, abort if any member failed.
        if (
            label in ALWAYS_RUN_STAGES
            and always_run_failed
            and (i + 1 >= len(all_stages) or all_stages[i + 1][0] not in ALWAYS_RUN_STAGES)
        ):
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
