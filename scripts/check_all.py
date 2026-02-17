"""Full CI pipeline: Lock → Audit → Lint → Type → Unit → Int → Containerfile → Build → Smoke → E2E.

Usage:
    python3 scripts/check_all.py

Orchestrates 11 stages in order and prints a unified final summary
with colored pass/fail indicators.

Non-critical stages (Lock-File Check, Dep Audit, Containerfile Lint)
may fail without aborting the pipeline; their results are still
reported in the summary and affect the exit code.

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
from test import cmd_e2e, cmd_integration, cmd_smoke, cmd_unit

# ── Project root = parent of scripts/ ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Total number of stages in the pipeline
TOTAL_STAGES = 11

# Result type: (label, passed_or_none, elapsed)
StageResult = tuple[str, bool | None, float]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _stage_header(num: int, label: str) -> None:
    """Print a prominent stage header with progress indicator."""
    progress = f"[{num}/{TOTAL_STAGES}]"
    print(f"\n{Colors.HEADER}{Colors.BOLD}")
    print(f"{'═' * 60}")
    print(f"  {progress}  {label}")
    print(f"{'═' * 60}{Colors.ENDC}")


def _run_stage(num: int, label: str, func: Callable[[], None]) -> StageResult:
    """Run a pipeline stage, measure time, catch failures.

    Returns (label, passed, elapsed_seconds).
    """
    _stage_header(num, label)
    start = time.monotonic()
    try:
        func()
        elapsed = time.monotonic() - start
        print_success(f"{label} — {fmt_duration(elapsed)}")
        return label, True, elapsed
    except SystemExit as e:
        elapsed = time.monotonic() - start
        if e.code == 0 or e.code is None:
            print_success(f"{label} — {fmt_duration(elapsed)}")
            return label, True, elapsed
        print_error(f"{label} FAILED (exit {e.code}) — {fmt_duration(elapsed)}")
        return label, False, elapsed
    except Exception as e:
        elapsed = time.monotonic() - start
        print_error(f"{label} FAILED — {e} — {fmt_duration(elapsed)}")
        return label, False, elapsed


# Stages that may fail without aborting the pipeline.
# Their result is still shown in the summary and affects the exit code.
NON_CRITICAL_STAGES: set[str] = {"Lock-File Check", "Dep Audit", "Containerfile Lint"}


# ── Stage Functions ───────────────────────────────────────────────────────────


def _stage_lock_check() -> None:
    """Stage 1: Verify uv.lock is in sync with pyproject.toml."""
    result = subprocess.run(["uv", "lock", "--check"], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def _stage_dep_audit() -> None:
    """Stage 2: Security audit of dependencies via pip-audit."""
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


def _stage_unit_tests() -> None:
    """Stage 5: Unit tests with per-package coverage."""
    result = subprocess.run(cmd_unit(), cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def _stage_integration_tests() -> None:
    """Stage 6: Integration tests with per-package coverage."""
    result = subprocess.run(cmd_integration(), cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def _stage_containerfile_lint() -> None:
    """Stage 7: Lint Containerfiles with hadolint (skips if not installed)."""
    if not shutil.which("hadolint"):
        print("  ⚠️  hadolint not found — skipping Containerfile lint.")
        print("  Install: https://github.com/hadolint/hadolint#install")
        return

    containerfiles = sorted(PROJECT_ROOT.glob("services/*/Containerfile"))
    if not containerfiles:
        print("  No Containerfiles found.")
        return

    failed = False
    for cf in containerfiles:
        print(f"  Linting {cf.relative_to(PROJECT_ROOT)} ...")
        result = subprocess.run(["hadolint", str(cf)], cwd=PROJECT_ROOT)
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


def _stage_smoke_tests() -> None:
    """Stage 10: Smoke tests via testcontainers (self-contained).

    Testcontainers spins up isolated, ephemeral containers with
    random ports. No compose start/stop needed, no port conflicts.
    """
    result = subprocess.run(cmd_smoke(), cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def _stage_e2e_tests() -> None:
    """Stage 11: End-to-end browser tests via Playwright."""
    result = subprocess.run(cmd_e2e(), cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


# ── Main Pipeline ─────────────────────────────────────────────────────────────


def main() -> None:
    """Run the full CI pipeline with unified summary."""
    ensure_initialized()

    pipeline_start = time.monotonic()

    stages: list[StageResult] = []

    def record(label: str, num: int, func: Callable[[], None]) -> bool:
        """Run a stage and record the result. Returns True if passed."""
        result = _run_stage(num, label, func)
        stages.append(result)
        return result[1] is True

    # ── All stages in order (each builds on the previous) ───────────────
    all_stages: list[tuple[str, int, Callable[[], None]]] = [
        ("Lock-File Check", 1, _stage_lock_check),
        ("Dep Audit", 2, _stage_dep_audit),
        ("Ruff Lint", 3, _stage_ruff),
        ("Mypy", 4, _stage_mypy),
        ("Unit Tests", 5, _stage_unit_tests),
        ("Integration Tests", 6, _stage_integration_tests),
        ("Containerfile Lint", 7, _stage_containerfile_lint),
        ("Clear", 8, _stage_clear),
        ("Build Images", 9, _stage_build),
        ("Smoke Tests", 10, _stage_smoke_tests),
        ("E2E Tests", 11, _stage_e2e_tests),
    ]

    # ── Early-fail for critical stages; non-critical stages continue ──
    for label, num, func in all_stages:
        if not record(label, num, func) and label not in NON_CRITICAL_STAGES:
            # Mark all remaining stages as skipped
            for skip_label, _skip_num, _ in all_stages[num:]:
                stages.append((skip_label, None, 0.0))
            break

    # ── Final Summary ─────────────────────────────────────────────────────
    pipeline_elapsed = time.monotonic() - pipeline_start
    _print_summary(stages, pipeline_elapsed)

    # Exit with error if any stage failed
    if any(passed is False for _, passed, _ in stages):
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
    skipped_count = 0

    # Find max elapsed for bar normalization (longest stage = full bar)
    max_elapsed = max((e for _, p, e in stages if p is not None), default=1.0) or 1.0
    max_label = max(len(label) for label, _, _ in stages)

    for label, passed, elapsed in stages:
        if passed is None:
            icon = f"{Colors.WARNING}⏭️  SKIP{Colors.ENDC}"
            skipped_count += 1
            bar_str = f"  {'·' * bar_width}"
            time_str = ""
        elif passed:
            icon = f"{Colors.OKGREEN}✅ PASS{Colors.ENDC}"
            passed_count += 1
            filled = int(min(elapsed / max_elapsed, 1.0) * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            bar_str = f"  {Colors.OKGREEN}{bar}{Colors.ENDC}"
            time_str = f"  {fmt_duration(elapsed)}"
        else:
            icon = f"{Colors.FAIL}❌ FAIL{Colors.ENDC}"
            failed_count += 1
            filled = int(min(elapsed / max_elapsed, 1.0) * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            bar_str = f"  {Colors.FAIL}{bar}{Colors.ENDC}"
            time_str = f"  {fmt_duration(elapsed)}"

        print(f"  {icon}  {label:<{max_label}}{bar_str}{time_str}")

    total_label = f"{'TOTAL':<{max_label + 10}}"
    total_bar = "─" * bar_width
    total_time = f"{Colors.BOLD}{fmt_duration(total_elapsed)}{Colors.ENDC}"
    print(f"\n  {total_label}{total_bar}  {total_time}")

    if failed_count == 0 and skipped_count == 0:
        print(
            f"\n  {Colors.OKGREEN}{Colors.BOLD}🎉 All {TOTAL_STAGES} stages passed!{Colors.ENDC}\n"
        )
    elif failed_count > 0:
        print(f"\n  {Colors.FAIL}{Colors.BOLD}💥 {failed_count} stage(s) failed!{Colors.ENDC}\n")
    else:
        print(
            f"\n  {Colors.WARNING}{Colors.BOLD}"
            f"⚠️  {skipped_count} stage(s) skipped due to earlier failures."
            f"{Colors.ENDC}\n"
        )


if __name__ == "__main__":
    main()
