#!/usr/bin/env python3
"""Centralized test runner for all pytest-based test suites.

Single source of truth for pytest commands — used by both the justfile
targets (just test-unit, just test-int, …) and the CI pipeline scripts
(check.py, check_all.py).

Usage:
    python3 scripts/test.py unit          # fast mocked tests
    python3 scripts/test.py integration   # testcontainers DB tests
    python3 scripts/test.py system        # full-stack lifecycle (Podman, no HW)
    python3 scripts/test.py system_hw     # hardware system tests (USB mic)
    python3 scripts/test.py smoke         # container smoke tests
    python3 scripts/test.py e2e           # Playwright browser tests
    python3 scripts/test.py all           # all non-HW tests (unit+int+system+smoke+e2e)
"""

import os
import subprocess
import sys
from pathlib import Path

from common import (
    Colors,
    discover_cov_args,
    ensure_initialized,
    print_error,
    print_header,
    print_success,
)

# ── Project root = parent of scripts/ ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Per-suite parallel workers (0 = sequential).
# Override via SILVASONIC_{UNIT,INTEGRATION,SYSTEM}_WORKERS env vars.
UNIT_WORKERS = int(os.environ.get("SILVASONIC_UNIT_WORKERS", "10"))
INTEGRATION_WORKERS = int(os.environ.get("SILVASONIC_INTEGRATION_WORKERS", "8"))
# System tests: 6 is the sweet-spot.  At 8+ workers the rootless Podman
# socket becomes a bottleneck (60s read timeouts on the API).
SYSTEM_WORKERS = int(os.environ.get("SILVASONIC_SYSTEM_WORKERS", "6"))


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
        str(UNIT_WORKERS),
        "--tb=short",
        "-q",
        "-rs",
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
        "-n",
        str(INTEGRATION_WORKERS),
        "--tb=short",
        "-q",
        "-rs",
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


def cmd_system() -> list[str]:
    """Build the pytest command for system lifecycle tests."""
    return [
        "uv",
        "run",
        "pytest",
        "-m",
        "system",
        "-n",
        str(SYSTEM_WORKERS),
        "-p",
        "no:cov",
        "--override-ini",
        "addopts=",
        "--override-ini",
        "timeout=120",
        "--tb=short",
        "-v",
    ]


def cmd_system_hw() -> list[str]:
    """Build the pytest command for hardware system tests."""
    return [
        "uv",
        "run",
        "pytest",
        "-m",
        "system_hw",
        "-s",  # Disable capture — interactive input() in hot-plug tests
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


def cmd_test() -> list[str]:
    """Build the pytest command for quick dev tests (unit + integration)."""
    return [
        "uv",
        "run",
        "pytest",
        "-m",
        "unit or integration",
        "-n",
        str(INTEGRATION_WORKERS),
        "--tb=short",
        "-q",
        "-rs",
        *discover_cov_args(),
        "--cov-report=term-missing",
    ]


def cmd_all() -> list[str]:
    """Build the pytest command for all tests (excl. system_hw)."""
    return [
        "uv",
        "run",
        "pytest",
        "-m",
        "unit or integration or system or smoke or e2e",
        "-n",
        str(SYSTEM_WORKERS),
        "-p",
        "no:cov",
        "--override-ini",
        "addopts=",
        "--override-ini",
        "timeout=120",
        "--tb=short",
        "-v",
    ]


def cmd_cov_all() -> list[str]:
    """Build the pytest command for combined coverage (unit+int+system+smoke+e2e)."""
    return [
        "uv",
        "run",
        "pytest",
        "-m",
        "unit or integration or system or smoke or e2e",
        "-n",
        str(SYSTEM_WORKERS),
        "--tb=short",
        "-q",
        "-rs",
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


def run_system() -> int:
    """Run system lifecycle tests. Returns exit code."""
    return _pytest("System", cmd_system())


def _preflight_hw() -> None:
    """Print a pre-flight diagnostic banner for hardware tests."""
    sep = "═" * 58
    thin = "─" * 58
    h = f"{Colors.BOLD}{Colors.HEADER}"
    e = Colors.ENDC
    ok = f"{Colors.OKGREEN}✅{e}"
    fail = f"{Colors.FAIL}❌{e}"

    print(f"\n{h}\n{sep}")
    print("  🎤  Hardware Test Pre-Flight Check (UltraMic 384K)")
    print(f"{sep}{e}")

    # 1. USB-Audio device
    usb_found = False
    usb_detail = "NOT FOUND"
    cards_path = Path("/proc/asound/cards")
    try:
        text = cards_path.read_text()
        if "USB-Audio" in text:
            usb_found = True
            # Extract name from the card line
            for line in text.splitlines():
                if "USB-Audio" in line:
                    usb_detail = line.split("- ", 1)[-1].strip()
                    break
    except (FileNotFoundError, PermissionError):
        pass

    icon = ok if usb_found else fail
    print(f"  {icon}  USB-Audio device .... {usb_detail}")

    # 2. Podman socket — use `podman info` instead of Path.exists() because
    #    systemd socket-activated files are not visible via stat().
    socket_ok = (
        subprocess.run(
            ["podman", "info", "--format", "{{.Host.RemoteSocket.Path}}"],
            capture_output=True,
            timeout=5,
        ).returncode
        == 0
    )
    socket_detail = "podman info OK" if socket_ok else "unreachable"
    icon = ok if socket_ok else fail
    print(f"  {icon}  Podman socket ...... {socket_detail}")

    # 3. Recorder image
    image = "localhost/silvasonic_recorder:latest"
    image_ok = (
        subprocess.run(
            ["podman", "image", "exists", image],
            capture_output=True,
        ).returncode
        == 0
    )
    icon = ok if image_ok else fail
    print(f"  {icon}  Recorder image ..... {image}")

    # 4. Check for conflicting background services
    conflict_ok = True
    conflict_detail = "no background services"
    try:
        cs = subprocess.run(
            [
                "podman",
                "ps",
                "--filter",
                "name=silvasonic-controller",
                "--filter",
                "name=silvasonic-recorder",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        running = [line.strip() for line in cs.stdout.strip().splitlines() if line.strip()]
        if cs.returncode == 0 and running:
            conflict_ok = False
            conflict_detail = "conflict: " + ", ".join(running)
            icon = fail
        else:
            icon = ok
    except Exception:
        icon = fail
        conflict_ok = False
        conflict_detail = "podman ps failed"

    print(f"  {icon}  Background services  {conflict_detail}")

    print(f"  {thin}")

    if usb_found and socket_ok and image_ok and conflict_ok:
        print(
            f"  {Colors.OKGREEN}{Colors.BOLD}"
            f"✅ All prerequisites met — running full test suite."
            f"{e}",
        )
    else:
        hints: list[str] = []
        if not usb_found:
            hints.append(
                "  → Connect UltraMic 384K (VID:0869 PID:0389)\n"
                "  → Verify: cat /proc/asound/cards | grep USB-Audio",
            )
        if not socket_ok:
            hints.append(
                "  → Start Podman: systemctl --user start podman.socket",
            )
        if not image_ok:
            hints.append("  → Build images: just build")
        if not conflict_ok:
            hints.append(
                "  → Stop background services: just stop\n"
                "  → ALSA hardware requires exclusive access to avoid 'Device or resource busy'."
            )

        print(
            f"  {Colors.WARNING}{Colors.BOLD}"
            f"⚠️  Prerequisites missing or blocked — cannot run hardware tests."
            f"{e}",
        )
        for hint in hints:
            print(hint)

    print(f"{h}{sep}{e}\n")
    if not conflict_ok:
        sys.exit(1)


def run_system_hw() -> int:
    """Run hardware system tests. Returns exit code."""
    _preflight_hw()
    return _pytest("System-HW", cmd_system_hw())


def run_e2e() -> int:
    """Run E2E tests. Returns exit code."""
    return _pytest("E2E", cmd_e2e())


def run_test() -> int:
    """Run quick dev tests (unit + integration). Returns exit code."""
    return _pytest("Test", cmd_test())


def run_all() -> int:
    """Run all non-HW tests (unit+int+system+smoke+e2e). Returns exit code."""
    return _pytest("All", cmd_all())


def run_cov_all() -> int:
    """Run combined coverage tests. Returns exit code."""
    return _pytest("Cov-All", cmd_cov_all())


# ── CLI entry point ───────────────────────────────────────────────────────────

SUITES = {
    "unit": run_unit,
    "integration": run_integration,
    "int": run_integration,
    "system": run_system,
    "system_hw": run_system_hw,
    "smoke": run_smoke,
    "e2e": run_e2e,
    "test": run_test,
    "all": run_all,
    "cov-all": run_cov_all,
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
