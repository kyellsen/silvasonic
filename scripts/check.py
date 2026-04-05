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
from collections.abc import Callable
from pathlib import Path

from common import ensure_initialized
from pipeline import run_pipeline
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


def make_cmd_runner(cmd: list[str]) -> Callable[[], None]:
    """Create a runner function for simple subprocess commands."""

    def runner() -> None:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT)
        if result.returncode != 0:
            sys.exit(result.returncode)

    return runner


def _run_pytest_stage(cmd_func: Callable[[], list[str]], label: str) -> int:
    """Run a pytest command, parse JUnit XML for skipped tests, return skip count."""
    import xml.etree.ElementTree as ET

    xml_path = PROJECT_ROOT / f".tmp/junit_{label.strip().replace(' ', '_').lower()}.xml"
    xml_path.parent.mkdir(exist_ok=True)
    if xml_path.exists():
        xml_path.unlink()

    cmd = [*cmd_func(), f"--junitxml={xml_path}"]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)

    if result.returncode not in (0, 5):
        sys.exit(result.returncode)

    skipped = 0
    if xml_path.exists():
        try:
            tree = ET.parse(xml_path)
            testsuite = tree.getroot()
            if testsuite.tag == "testsuites" and len(testsuite) > 0:
                testsuite = testsuite[0]
            skipped = int(testsuite.attrib.get("skipped", 0))
        except Exception:
            pass

    return skipped


def main() -> None:
    """Run lock-check, ruff, mypy, and unit tests sequentially.

    Non-critical stages (Lock-File Check) may fail without aborting
    the pipeline.  Critical stages abort on first failure.
    """
    ensure_initialized()

    is_verify = "--verify" in sys.argv
    targets: list[str] = [arg for arg in sys.argv[1:] if arg != "--verify"]
    if not targets:
        targets = ["."]

    all_stages: list[tuple[str, Callable[[], None | int]]] = [
        ("Lock-File Check", make_cmd_runner(["uv", "lock", "--check"])),
        ("Ruff Lint", make_cmd_runner(["uv", "run", "ruff", "check", *targets])),
        ("Mypy", make_cmd_runner(["uv", "run", "mypy", *targets])),
        ("Unit Tests", lambda: _run_pytest_stage(cmd_unit, "Unit Tests")),
    ]

    if is_verify:
        from test import cmd_integration

        all_stages.append(
            (
                "Integration Tests",
                lambda: _run_pytest_stage(cmd_integration, "Integration Tests"),
            )
        )

    passed = run_pipeline(
        all_stages=all_stages,
        non_critical_stages=NON_CRITICAL_STAGES,
        always_run_stages=ALWAYS_RUN_STAGES,
    )

    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
