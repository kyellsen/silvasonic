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
import time
from collections.abc import Callable
from pathlib import Path

from common import Colors, ensure_initialized, fmt_duration, print_error, print_success
from test import cmd_e2e, cmd_integration, cmd_smoke, cmd_system, cmd_unit

# ── Project root = parent of scripts/ ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Total number of stages in the pipeline
TOTAL_STAGES = 12

# Result type: (label, passed_or_none, elapsed, critical, skipped_count)
StageResult = tuple[str, bool | None, float, bool, int]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _stage_header(num: int, label: str) -> None:
    """Print a prominent stage header with progress indicator."""
    progress = f"[{num}/{TOTAL_STAGES}]"
    print(f"\n{Colors.HEADER}{Colors.BOLD}")
    print(f"{'═' * 60}")
    print(f"  {progress}  {label}")
    print(f"{'═' * 60}{Colors.ENDC}")


def _run_stage(
    num: int,
    label: str,
    func: Callable[[], None | int],
    *,
    critical: bool = True,
) -> StageResult:
    """Run a pipeline stage, measure time, catch failures.

    Returns (label, passed, elapsed_seconds, critical, skipped_count).
    """
    _stage_header(num, label)
    start = time.monotonic()
    skipped_count = 0
    try:
        res = func()
        if isinstance(res, int):
            skipped_count = res
        elapsed = time.monotonic() - start
        warn_msg = f" ({skipped_count} skipped)" if skipped_count > 0 else ""
        print_success(f"{label}{warn_msg} — {fmt_duration(elapsed)}")
        return label, True, elapsed, critical, skipped_count
    except SystemExit as e:
        elapsed = time.monotonic() - start
        if e.code == 0 or e.code is None:
            warn_msg = f" ({skipped_count} skipped)" if skipped_count > 0 else ""
            print_success(f"{label}{warn_msg} — {fmt_duration(elapsed)}")
            return label, True, elapsed, critical, skipped_count
        print_error(f"{label} FAILED (exit {e.code}) — {fmt_duration(elapsed)}")
        return label, False, elapsed, critical, skipped_count
    except Exception as e:
        elapsed = time.monotonic() - start
        print_error(f"{label} FAILED — {e} — {fmt_duration(elapsed)}")
        return label, False, elapsed, critical, skipped_count


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

    pipeline_start = time.monotonic()

    stages: list[StageResult] = []

    def record(label: str, num: int, func: Callable[[], None | int]) -> bool:
        """Run a stage and record the result. Returns True if passed."""
        critical = label not in NON_CRITICAL_STAGES
        result = _run_stage(num, label, func, critical=critical)
        stages.append(result)
        return result[1] is True

    # ── All stages in order (each builds on the previous) ───────────────
    all_stages: list[tuple[str, int, Callable[[], None | int]]] = [
        ("Lock-File Check", 1, _stage_lock_check),
        ("Dep Audit", 2, _stage_dep_audit),
        ("Containerfile Lint", 3, _stage_containerfile_lint),
        ("Ruff Lint", 4, _stage_ruff),
        ("Mypy", 5, _stage_mypy),
        ("Unit Tests", 6, _stage_unit_tests),
        ("Integration Tests", 7, _stage_integration_tests),
        ("Clear", 8, _stage_clear),
        ("Build Images", 9, _stage_build),
        ("System Tests", 10, _stage_system_tests),
        ("Smoke Tests", 11, _stage_smoke_tests),
        ("E2E Tests", 12, _stage_e2e_tests),
    ]

    # ── Run stages with always-run group support ──────────────────────
    always_run_failed = False
    for idx, stage_entry in enumerate(all_stages):
        label: str = stage_entry[0]
        num: int = stage_entry[1]
        func: Callable[[], None | int] = stage_entry[2]
        if label in SKIPPED_BY_DEFAULT:
            _stage_header(num, label)
            print(f"  ⏩  {label} skipped by default (SKIPPED_BY_DEFAULT).")
            stages.append((label, None, 0.0, True, 0))
            continue
        passed = record(label, num, func)
        if not passed:
            if label in ALWAYS_RUN_STAGES:
                # Record failure but keep going so sibling stages run.
                always_run_failed = True
            elif label not in NON_CRITICAL_STAGES:
                # Hard abort for other critical stages.
                for skip_label, _skip_num, _ in all_stages[idx + 1 :]:
                    stages.append((skip_label, None, 0.0, True, 0))
                break

        # After leaving the always-run group, abort if any member failed.
        if (
            label in ALWAYS_RUN_STAGES
            and always_run_failed
            and (idx + 1 >= len(all_stages) or all_stages[idx + 1][0] not in ALWAYS_RUN_STAGES)
        ):
            for skip_label, _skip_num, _ in all_stages[idx + 1 :]:
                stages.append((skip_label, None, 0.0, True, 0))
            break

    # ── Final Summary ─────────────────────────────────────────────────────
    pipeline_elapsed = time.monotonic() - pipeline_start
    _print_summary(stages, pipeline_elapsed)

    # Exit with error only if a CRITICAL stage failed.
    # Non-critical stages (e.g. Dep Audit) are reported but do not block.
    if any(passed is False and critical for _, passed, _, critical, _ in stages):
        sys.exit(1)


def _print_summary(
    stages: list[StageResult],
    total_elapsed: float,
) -> None:
    """Print the final unified summary with colored pass/fail indicators and timing bars."""
    bar_width = 20

    print(f"\n\n{Colors.BOLD}")
    print(f"{'═' * 60}")
    print("  📋  FULL PIPELINE SUMMARY")
    print(f"{'═' * 60}{Colors.ENDC}")

    passed_count = 0
    failed_count = 0
    warned_count = 0
    skipped_count_total = 0

    # Find max elapsed for bar normalization (longest stage = full bar)
    max_elapsed = max((e for _, p, e, _c, _s in stages if p is not None), default=1.0) or 1.0
    max_label = max(len(label) for label, _, _, _, _ in stages)
    max_pad = max_label + 12

    for label, passed, elapsed, critical, tests_skipped in stages:
        if passed is None:
            icon = f"{Colors.WARNING}⏭️  SKIP{Colors.ENDC}"
            skipped_count_total += 1
            bar_str = f"  {'·' * bar_width}"
            time_str = ""
            label_display = label
        elif passed:
            if tests_skipped > 0:
                icon = f"{Colors.WARNING}⚠️  WARN{Colors.ENDC}"
                warned_count += 1
                label_display = f"{label} ({tests_skipped} skips)"
            else:
                icon = f"{Colors.OKGREEN}✅ PASS{Colors.ENDC}"
                passed_count += 1
                label_display = label

            filled = int(min(elapsed / max_elapsed, 1.0) * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            color = Colors.WARNING if tests_skipped > 0 else Colors.OKGREEN
            bar_str = f"  {color}{bar}{Colors.ENDC}"
            time_str = f"  {fmt_duration(elapsed)}"
        elif not critical:
            # Non-critical failure → warning (does not affect exit code).
            icon = f"{Colors.WARNING}⚠️  WARN{Colors.ENDC}"
            warned_count += 1
            label_display = label
            filled = int(min(elapsed / max_elapsed, 1.0) * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            bar_str = f"  {Colors.WARNING}{bar}{Colors.ENDC}"
            time_str = f"  {fmt_duration(elapsed)}"
        else:
            icon = f"{Colors.FAIL}❌ FAIL{Colors.ENDC}"
            failed_count += 1
            label_display = label
            filled = int(min(elapsed / max_elapsed, 1.0) * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            bar_str = f"  {Colors.FAIL}{bar}{Colors.ENDC}"
            time_str = f"  {fmt_duration(elapsed)}"

        print(f"  {icon}  {label_display:<{max_pad}}{bar_str}{time_str}")

    total_label = f"{'TOTAL':<{max_pad + 10}}"
    total_bar = "─" * bar_width
    total_time = f"{Colors.BOLD}{fmt_duration(total_elapsed)}{Colors.ENDC}"
    print(f"\n  {total_label}{total_bar}  {total_time}")

    if failed_count == 0 and warned_count == 0 and skipped_count_total == 0:
        print(
            f"\n  {Colors.OKGREEN}{Colors.BOLD}🎉 All {TOTAL_STAGES} stages passed!{Colors.ENDC}\n"
        )
    elif failed_count > 0:
        print(f"\n  {Colors.FAIL}{Colors.BOLD}💥 {failed_count} stage(s) failed!{Colors.ENDC}\n")
    elif warned_count > 0 and skipped_count_total == 0:
        print(
            f"\n  {Colors.OKGREEN}{Colors.BOLD}"
            f"✅ Pipeline passed"
            f"{Colors.ENDC}"
            f" {Colors.WARNING}({warned_count} non-critical warning(s)){Colors.ENDC}\n"
        )
    else:
        print(
            f"\n  {Colors.WARNING}{Colors.BOLD}"
            f"⚠️  {skipped_count_total} stage(s) skipped due to earlier failures."
            f"{Colors.ENDC}\n"
        )

    # Always remind about manual hardware tests
    print(
        f"  {Colors.WARNING}🎤 Hardware tests excluded from this pipeline.{Colors.ENDC}\n"
        f"  {Colors.WARNING}   Run manually with USB microphone connected:"
        f" {Colors.BOLD}just test-hw-all{Colors.ENDC}\n"
    )


if __name__ == "__main__":
    main()
