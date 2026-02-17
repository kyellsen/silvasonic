"""Full CI pipeline: Lint → Type → Test → Build → Smoke → Clean.

Usage:
    uv run python scripts/check_full.py

Orchestrates 8 stages in order, guarantees cleanup via try/finally,
and prints a unified final summary with colored pass/fail indicators.
"""

import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from common import Colors, fmt_duration, print_error, print_success

# ── Project root = parent of scripts/ ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Total number of stages in the pipeline
TOTAL_STAGES = 8

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


# ── Stage Functions ───────────────────────────────────────────────────────────


def _stage_ruff() -> None:
    """Stage 1: Ruff lint."""
    result = subprocess.run(["uv", "run", "ruff", "check", "."], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def _stage_mypy() -> None:
    """Stage 2: Mypy type checking."""
    result = subprocess.run(["uv", "run", "mypy", "."], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def _stage_unit_tests() -> None:
    """Stage 3: Unit tests."""
    result = subprocess.run(
        ["uv", "run", "pytest", "-m", "unit", "--tb=short", "-q"],
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)


def _stage_clear() -> None:
    """Stage 4: Clear caches and build artifacts."""
    import clear

    clear.main()


def _stage_clean() -> None:
    """Stage 8 (partial): Full clean (containers + workspace)."""
    import clean

    clean.main()


def _stage_build() -> None:
    """Stage 5: Build container images."""
    import build

    build.main()


def _stage_start() -> None:
    """Stage 6: Start services."""
    import start

    start.main()


def _stage_smoke_tests() -> None:
    """Stage 7: Smoke tests (with coverage disabled to avoid warnings)."""
    result = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "-m",
            "smoke",
            "-p",
            "no:cov",  # Disable coverage plugin (no "No data" warnings)
            "--override-ini",
            "addopts=",  # Clear global addopts to avoid --cov
            "--tb=short",
            "-q",
        ],
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)


def _stage_stop_and_clean() -> None:
    """Stage 8: Stop services and clean up."""
    import stop

    stop.main()

    import clean

    clean.main()


# ── Main Pipeline ─────────────────────────────────────────────────────────────


def main() -> None:
    """Run the full CI pipeline with unified summary."""
    pipeline_start = time.monotonic()

    stages: list[StageResult] = []

    def record(label: str, num: int, func: Callable[[], None]) -> bool:
        """Run a stage and record the result. Returns True if passed."""
        result = _run_stage(num, label, func)
        stages.append(result)
        return result[1] is True

    # ── Stages 1-3: Static checks (always run all three) ─────────────────
    record("Ruff Lint", 1, _stage_ruff)
    record("Mypy", 2, _stage_mypy)
    record("Unit Tests", 3, _stage_unit_tests)

    # Check if static checks passed before proceeding to container stages
    static_ok = all(passed is True for _, passed, _ in stages)

    if not static_ok:
        # Skip container stages if static checks failed
        for label in ["Clear", "Build Images", "Start Services", "Smoke Tests", "Stop & Clean"]:
            stages.append((label, None, 0.0))
    else:
        # ── Stage 4: Clear ────────────────────────────────────────────────
        record("Clear", 4, _stage_clear)

        # ── Stages 5-7: Container pipeline with guaranteed cleanup ────────
        try:
            record("Build Images", 5, _stage_build)
            record("Start Services", 6, _stage_start)
            record("Smoke Tests", 7, _stage_smoke_tests)
        finally:
            # ── Stage 8: Always clean up ──────────────────────────────────
            record("Stop & Clean", 8, _stage_stop_and_clean)

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
