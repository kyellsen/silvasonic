"""Pipeline execution engine for Silvasonic CLI scripts.

Provides the `run_pipeline` orchestration and the beautiful timing
summary output used by `just ci`, `just check`, and `just verify`.
"""

import time
from collections.abc import Callable

from common import Colors, fmt_duration, print_error, print_success

# Result type: (label, passed_or_none, elapsed, critical, skipped_count)
StageResult = tuple[str, bool | None, float, bool, int]


def _stage_header(num: int, label: str, total_stages: int) -> None:
    """Print a prominent stage header with progress indicator."""
    progress = f"[{num}/{total_stages}]"
    print(f"\n{Colors.HEADER}{Colors.BOLD}")
    print(f"{'═' * 60}")
    print(f"  {progress}  {label}")
    print(f"{'═' * 60}{Colors.ENDC}")


def _run_stage(
    num: int,
    label: str,
    func: Callable[[], None | int],
    total_stages: int,
    critical: bool,
) -> StageResult:
    """Run a pipeline stage, measure time, catch failures.

    Returns (label, passed, elapsed_seconds, critical, skipped_count).
    """
    _stage_header(num, label, total_stages)
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


def _print_summary(
    stages: list[StageResult],
    total_elapsed: float,
    total_stages: int,
    footer_msg: str | None = None,
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
    max_label = max((len(label) for label, _, _, _, _ in stages), default=10)
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
            f"\n  {Colors.OKGREEN}{Colors.BOLD}🎉 All {total_stages} stages passed!{Colors.ENDC}\n"
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

    if footer_msg:
        print(f"{footer_msg}\n")


def run_pipeline(
    all_stages: list[tuple[str, Callable[[], None | int]]],
    non_critical_stages: set[str] | None = None,
    always_run_stages: set[str] | None = None,
    skipped_by_default: set[str] | None = None,
    footer_msg: str | None = None,
) -> bool:
    """Run a pipeline of stages, handling skip/failure logic, and print summary.

    Returns True if the pipeline is considered successful (no critical stages failed).
    """
    if non_critical_stages is None:
        non_critical_stages = set()
    if always_run_stages is None:
        always_run_stages = set()
    if skipped_by_default is None:
        skipped_by_default = set()

    pipeline_start = time.monotonic()
    total_stages = len(all_stages)
    stages: list[StageResult] = []

    def record(label: str, num: int, func: Callable[[], None | int]) -> bool:
        """Run a stage and record the result. Returns True if passed."""
        critical = label not in non_critical_stages
        result = _run_stage(num, label, func, total_stages, critical)
        stages.append(result)
        return result[1] is True

    always_run_failed = False
    for idx, (label, func) in enumerate(all_stages):
        num = idx + 1
        if label in skipped_by_default:
            _stage_header(num, label, total_stages)
            print(f"  ⏩  {label} skipped by default (SKIPPED_BY_DEFAULT).")
            stages.append((label, None, 0.0, True, 0))
            continue
        passed = record(label, num, func)
        if not passed:
            if label in always_run_stages:
                # Record failure but keep going so sibling stages run.
                always_run_failed = True
            elif label not in non_critical_stages:
                # Hard abort for other critical stages.
                for skip_label, _ in all_stages[idx + 1 :]:
                    stages.append((skip_label, None, 0.0, True, 0))
                break

        # After leaving the always-run group, abort if any member failed.
        if (
            label in always_run_stages
            and always_run_failed
            and (idx + 1 >= len(all_stages) or all_stages[idx + 1][0] not in always_run_stages)
        ):
            for skip_label, _ in all_stages[idx + 1 :]:
                stages.append((skip_label, None, 0.0, True, 0))
            break

    pipeline_elapsed = time.monotonic() - pipeline_start
    _print_summary(stages, pipeline_elapsed, total_stages, footer_msg)

    # Return False if any CRITICAL stage failed.
    # Non-critical stages are reported but do not block.
    return not any(passed is False and critical for _, passed, _, critical, _ in stages)
