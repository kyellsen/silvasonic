"""Full CI pipeline.

Lock → Audit → Containerfile → Lint → Type → Unit → Int → Clear → Build → System → Smoke → E2E.

Dep Audit runs pip-audit to check for known vulnerabilities in dependencies.

Usage:
    python3 scripts/ci.py

Orchestrates 12 stages in order and prints a unified final summary
with colored pass/fail indicators.

Non-critical stages (Lock-File Check, Dep Audit, Containerfile Lint)
may fail without aborting the pipeline; their results are still
reported in the summary and affect the exit code.

Ruff Lint and Mypy always both run so the developer gets full
lint+type feedback in a single pass.  If either fails the pipeline
aborts before moving on to the test stages.

Smoke tests are self-contained via testcontainers — no need to
start/stop the real compose stack.
"""

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from common import Colors, ensure_initialized
from test import cmd_e2e, cmd_integration, cmd_smoke, cmd_system, cmd_unit

# ── Project root = parent of scripts/ ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Stages that may fail without aborting the pipeline.
# Their result is still shown in the summary and affects the exit code.
NON_CRITICAL_STAGES: set[str] = {"Lock-File Check", "Dep Audit", "Containerfile Lint"}

# Stages that always run even if a sibling fails.
# After all ALWAYS_RUN stages have executed, the pipeline aborts if
# any of them failed.
ALWAYS_RUN_STAGES: set[str] = {"Ruff Lint", "Mypy"}

# Stages that are skipped by default (dev convenience).
# Remove a stage name from this set to re-enable it.
SKIPPED_BY_DEFAULT: set[str] = set()


# ── Stage Functions ───────────────────────────────────────────────────────────


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


def _stage_lock_check() -> None:
    """Stage 1: Verify uv.lock is in sync with pyproject.toml."""
    result = subprocess.run(["uv", "lock", "--check"], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def _stage_dep_audit() -> None:
    """Stage 2: Security audit of dependencies via pip-audit.

    Hinweis: Wir ignorieren vorerst CVE-2026-4539 (pygments), da noch kein Fix
    verfügbar ist. Wir nutzen absichtlich kein `--ignore-vuln`, damit der Fehler
    weiterhin im Log angezeigt wird und wir an das Update erinnert werden!
    """
    result = subprocess.run(["uv", "run", "pip-audit"], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def _stage_ruff() -> None:
    """Stage 3: Ruff lint."""
    result = subprocess.run(["uv", "run", "ruff", "check", "."], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def _stage_mypy() -> None:
    """Stage 4: Mypy strict type checking (incl. services + packages)."""
    result = subprocess.run(["uv", "run", "mypy", "."], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def _stage_unit_tests() -> int:
    """Stage 5: Unit tests with per-package coverage."""
    return _run_pytest_stage(cmd_unit, "Unit Tests")


def _stage_integration_tests() -> int:
    """Stage 6: Integration tests with per-package coverage."""
    return _run_pytest_stage(cmd_integration, "Integration Tests")


def _stage_system_tests() -> int:
    """Stage 10: System lifecycle tests (real Podman, no hardware).

    Requires a running Podman socket and built images. Tests the full
    Controller lifecycle: seeding, device detection, reconciliation,
    container start/stop.
    """
    return _run_pytest_stage(cmd_system, "System Tests")


def _stage_containerfile_lint() -> None:
    """Stage 3: Lint Containerfiles with hadolint + validate Compose YAML."""
    failed = False

    # ── Hadolint ──────────────────────────────────────────────────────────
    if not shutil.which("hadolint"):
        print("  ⚠️  hadolint not found — skipping Containerfile lint.")
        print("  Install: https://github.com/hadolint/hadolint#install")
    else:
        containerfiles = sorted(PROJECT_ROOT.glob("services/*/Containerfile"))
        if not containerfiles:
            print("  No Containerfiles found.")
        else:
            for cf in containerfiles:
                print(f"  Linting {cf.relative_to(PROJECT_ROOT)} ...")
                result = subprocess.run(["hadolint", str(cf)], cwd=PROJECT_ROOT)
                if result.returncode != 0:
                    failed = True

    # ── Compose Validation ────────────────────────────────────────────────
    if not shutil.which("podman-compose"):
        print("  ⚠️  podman-compose not found — skipping Compose validation.")
    else:
        print("  Validating compose.yml ...")
        result = subprocess.run(
            ["podman-compose", "-f", "compose.yml", "config", "--quiet"],
            cwd=PROJECT_ROOT,
        )
        if result.returncode != 0:
            failed = True

    if failed:
        sys.exit(1)


def _stage_clear() -> None:
    """Stage 8: Clear caches and build artifacts."""
    import clear

    clear.main()


def _stage_build() -> None:
    """Stage 9: Build container images."""
    import build

    build.main()


def _stage_smoke_tests() -> int:
    """Stage 11: Smoke tests via testcontainers (self-contained).

    Testcontainers spins up isolated, ephemeral containers with
    random ports. No compose start/stop needed, no port conflicts.
    """
    return _run_pytest_stage(cmd_smoke, "Smoke Tests")


# Pytest exit code 5 means "no tests collected" — not a failure.
_PYTEST_NO_TESTS_COLLECTED = 5


def _stage_e2e_tests() -> None:
    """Stage 12: End-to-end browser tests via Playwright.

    Gracefully handles the case where no E2E tests exist yet
    (pytest exit code 5 = no tests collected).
    """
    result = subprocess.run(cmd_e2e(), cwd=PROJECT_ROOT)
    if result.returncode == _PYTEST_NO_TESTS_COLLECTED:
        print("  ⚠️  No E2E tests collected — skipping (expected until v0.9.0).")
        return
    if result.returncode != 0:
        sys.exit(result.returncode)


# ── Main Pipeline ─────────────────────────────────────────────────────────────


def main() -> None:
    """Run the full CI pipeline with unified summary."""
    ensure_initialized()

    all_stages: list[tuple[str, Callable[[], None | int]]] = [
        ("Lock-File Check", _stage_lock_check),
        ("Dep Audit", _stage_dep_audit),
        ("Containerfile Lint", _stage_containerfile_lint),
        ("Ruff Lint", _stage_ruff),
        ("Mypy", _stage_mypy),
        ("Unit Tests", _stage_unit_tests),
        ("Integration Tests", _stage_integration_tests),
        ("Clear", _stage_clear),
        ("Build Images", _stage_build),
        ("System Tests", _stage_system_tests),
        ("Smoke Tests", _stage_smoke_tests),
        ("E2E Tests", _stage_e2e_tests),
    ]

    from pipeline import run_pipeline

    footer_msg = (
        f"  {Colors.WARNING}🎤 Hardware tests excluded from this pipeline.{Colors.ENDC}\n"
        f"  {Colors.WARNING}   Run manually with USB microphone connected:"
        f" {Colors.BOLD}just test-hw-all{Colors.ENDC}"
    )

    passed = run_pipeline(
        all_stages=all_stages,
        non_critical_stages=NON_CRITICAL_STAGES,
        always_run_stages=ALWAYS_RUN_STAGES,
        skipped_by_default=SKIPPED_BY_DEFAULT,
        footer_msg=footer_msg,
    )

    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
