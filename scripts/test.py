#!/usr/bin/env python3
"""Centralized test runner for all pytest-based test suites.

Single source of truth for pytest commands — used by both the justfile
targets (just test-unit, just test-int, …) and the CI pipeline scripts
(check.py, check_all.py).

Usage:
    python3 scripts/test.py unit          # fast mocked tests
    python3 scripts/test.py integration   # testcontainers DB tests
    python3 scripts/test.py smoke         # container smoke tests
    python3 scripts/test.py e2e           # Playwright browser tests
    python3 scripts/test.py all           # unit + integration
"""

import subprocess
import sys
from pathlib import Path

from common import discover_cov_args, ensure_initialized, print_error, print_header, print_success

# ── Project root = parent of scripts/ ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Parallel workers for unit tests (0 = disabled)
PYTEST_WORKERS = 4


def _pytest(marker: str, cmd: list[str]) -> int:
    """Run pytest with the given command and return the exit code."""
    print_header(f"Running tests: {marker}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode == 0:
        print_success(f"{marker} tests passed.")
    else:
        print_error(f"{marker} tests FAILED (exit {result.returncode}).")
    return result.returncode


def cmd_unit() -> list[str]:
    """Build the pytest command for unit tests."""
    return [
        "uv",
        "run",
        "pytest",
        "-m",
        "unit",
        "-n",
        str(PYTEST_WORKERS),
        "--tb=short",
        "-q",
        *discover_cov_args(),
        "--cov-report=term-missing",
    ]


def cmd_integration() -> list[str]:
    """Build the pytest command for integration tests."""
    return [
        "uv",
        "run",
        "pytest",
        "-m",
        "integration",
        "--tb=short",
        "-q",
        *discover_cov_args(),
        "--cov-report=term-missing",
    ]


def cmd_smoke() -> list[str]:
    """Build the pytest command for smoke tests."""
    return [
        "uv",
        "run",
        "pytest",
        "-m",
        "smoke",
        "-p",
        "no:cov",
        "--override-ini",
        "addopts=",
        "--override-ini",
        "timeout=120",
        "--tb=short",
        "-v",
    ]


def cmd_e2e() -> list[str]:
    """Build the pytest command for E2E tests."""
    return [
        "uv",
        "run",
        "pytest",
        "-m",
        "e2e",
        "-p",
        "no:cov",
        "--override-ini",
        "addopts=",
        "--override-ini",
        "timeout=120",
        "--tb=short",
        "-v",
    ]


def cmd_all() -> list[str]:
    """Build the pytest command for all (unit + integration) tests."""
    return [
        "uv",
        "run",
        "pytest",
        "-m",
        "unit or integration",
        "--tb=short",
        "-q",
        *discover_cov_args(),
        "--cov-report=term-missing",
    ]


# ── Public API for check.py / check_all.py ──────────────────────────────────


def run_unit() -> int:
    """Run unit tests. Returns exit code."""
    return _pytest("Unit", cmd_unit())


def run_integration() -> int:
    """Run integration tests. Returns exit code."""
    return _pytest("Integration", cmd_integration())


def run_smoke() -> int:
    """Run smoke tests. Returns exit code."""
    return _pytest("Smoke", cmd_smoke())


def run_e2e() -> int:
    """Run E2E tests. Returns exit code."""
    return _pytest("E2E", cmd_e2e())


def run_all() -> int:
    """Run all tests (unit + integration). Returns exit code."""
    return _pytest("All", cmd_all())


# ── CLI entry point ───────────────────────────────────────────────────────────

SUITES = {
    "unit": run_unit,
    "integration": run_integration,
    "int": run_integration,
    "smoke": run_smoke,
    "e2e": run_e2e,
    "all": run_all,
}


def main() -> None:
    """Run a test suite by name from CLI arguments."""
    ensure_initialized()

    if len(sys.argv) < 2 or sys.argv[1] not in SUITES:
        valid = ", ".join(SUITES.keys())
        print_error(f"Usage: python3 scripts/test.py <{valid}>")
        sys.exit(2)

    suite = sys.argv[1]
    exit_code = SUITES[suite]()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
