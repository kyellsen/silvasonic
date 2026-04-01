"""Unit tests for silvasonic.controller.controller_stats module.

Tests the two-phase logging strategy:
  - Startup phase: container start/stop actions logged individually
  - Steady state: periodic summary logs with reconciliation metrics
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from silvasonic.controller.controller_stats import ControllerStats


@pytest.mark.unit
class TestControllerStatsStartupPhase:
    """Tests for the detailed startup-phase logging."""

    def test_in_startup_phase_initially(self) -> None:
        """Stats start in startup phase."""
        stats = ControllerStats(startup_duration_s=300.0)
        assert stats.in_startup_phase is True

    def test_startup_logs_container_start(self) -> None:
        """During startup, container starts are logged individually."""
        stats = ControllerStats(startup_duration_s=9999.0)

        with patch("silvasonic.controller.controller_stats.log") as mock_log:
            stats.record_container_start("silvasonic-recorder-ultramic-034f")

        start_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "controller.container_started"
        ]
        assert len(start_logs) == 1
        assert start_logs[0].kwargs["name"] == "silvasonic-recorder-ultramic-034f"

    def test_startup_logs_container_stop(self) -> None:
        """During startup, container stops are logged individually."""
        stats = ControllerStats(startup_duration_s=9999.0)

        with patch("silvasonic.controller.controller_stats.log") as mock_log:
            stats.record_container_stop("silvasonic-recorder-ultramic-034f")

        stop_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "controller.container_stopped"
        ]
        assert len(stop_logs) == 1


@pytest.mark.unit
class TestControllerStatsSteadyState:
    """Tests for the periodic summary in steady state."""

    def _make_steady_state_stats(
        self,
        summary_interval_s: float = 300.0,
    ) -> ControllerStats:
        """Create a ControllerStats past startup phase."""
        return ControllerStats(
            startup_duration_s=0.0,
            summary_interval_s=summary_interval_s,
        )

    def test_steady_state_no_individual_container_logs(self) -> None:
        """In steady state, container actions are not logged individually."""
        stats = self._make_steady_state_stats(summary_interval_s=9999.0)

        with patch("silvasonic.controller.controller_stats.log") as mock_log:
            stats.record_container_start("test-container")

        start_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "controller.container_started"
        ]
        assert len(start_logs) == 0

    def test_phase_transition_logged_once(self) -> None:
        """Startup -> steady transition is logged exactly once."""
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.controller.controller_stats.log") as mock_log:
            stats.record_reconcile_cycle()
            # Trigger summary check (which detects phase transition)
            stats.get_summary_if_due()
            # Second call should not log transition again
            stats.get_summary_if_due()

        transition_logs = [
            c
            for c in mock_log.info.call_args_list
            if c[0][0] == "controller.startup_phase_complete"
        ]
        assert len(transition_logs) == 1

    def test_summary_returned_after_interval(self) -> None:
        """Summary dict is returned when interval elapses."""
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.controller.controller_stats.log"):
            stats.record_reconcile_cycle()
            stats.record_reconcile_cycle()
            stats.record_container_start("container-a")
            stats.record_nudge()

            summary = stats.get_summary_if_due()

        assert summary is not None
        assert summary["interval_reconcile_cycles"] == 2
        assert summary["interval_containers_started"] == 1
        assert summary["interval_nudges"] == 1
        assert summary["total_reconcile_cycles"] == 2

    def test_summary_not_returned_before_interval(self) -> None:
        """Summary returns None before interval elapses."""
        stats = self._make_steady_state_stats(summary_interval_s=9999.0)

        with patch("silvasonic.controller.controller_stats.log"):
            stats.record_reconcile_cycle()
            summary = stats.get_summary_if_due()

        assert summary is None

    def test_summary_resets_interval_counters(self) -> None:
        """After emitting summary, interval counters reset to zero."""
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.controller.controller_stats.log"):
            stats.record_reconcile_cycle()
            stats.record_container_start("c1")
            first = stats.get_summary_if_due()

            # Only one more cycle
            stats.record_reconcile_cycle()
            second = stats.get_summary_if_due()

        assert first is not None
        assert second is not None
        assert second["interval_reconcile_cycles"] == 1
        assert second["interval_containers_started"] == 0
        # Totals still accumulate
        assert second["total_reconcile_cycles"] == 2

    def test_summary_includes_started_stopped_names(self) -> None:
        """Summary includes names of containers started/stopped."""
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.controller.controller_stats.log"):
            stats.record_container_start("c1")
            stats.record_container_stop("c2")
            summary = stats.get_summary_if_due()

        assert summary is not None
        started_names: list[str] = summary["interval_started_names"]  # type: ignore[assignment]
        stopped_names: list[str] = summary["interval_stopped_names"]  # type: ignore[assignment]
        assert "c1" in started_names
        assert "c2" in stopped_names

    def test_summary_includes_uptime(self) -> None:
        """Summary includes uptime_s field."""
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.controller.controller_stats.log"):
            stats.record_reconcile_cycle()
            summary = stats.get_summary_if_due()

        assert summary is not None
        assert "uptime_s" in summary
        assert float(summary["uptime_s"]) >= 0  # type: ignore[arg-type]


@pytest.mark.unit
class TestControllerStatsReconcileTracking:
    """Tests for reconciliation cycle and error tracking."""

    def test_cycle_count_accumulates(self) -> None:
        """Reconcile cycles accumulate in total counter."""
        stats = ControllerStats(startup_duration_s=9999.0)
        for _ in range(10):
            stats.record_reconcile_cycle()

        with patch("silvasonic.controller.controller_stats.log") as mock_log:
            stats.emit_final_summary()

        final_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "controller.final_summary"
        ]
        assert final_logs[0].kwargs["total_reconcile_cycles"] == 10

    def test_error_count_accumulates(self) -> None:
        """Reconcile errors accumulate in total counter."""
        stats = ControllerStats(startup_duration_s=9999.0)
        stats.record_reconcile_error()
        stats.record_reconcile_error()

        with patch("silvasonic.controller.controller_stats.log") as mock_log:
            stats.emit_final_summary()

        final_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "controller.final_summary"
        ]
        assert final_logs[0].kwargs["total_reconcile_errors"] == 2


@pytest.mark.unit
class TestControllerStatsNudgeTracking:
    """Tests for nudge counting."""

    def test_nudge_accumulates(self) -> None:
        """Nudges accumulate in both interval and total counters."""
        stats = ControllerStats(startup_duration_s=0.0, summary_interval_s=0.0)

        with patch("silvasonic.controller.controller_stats.log"):
            stats.record_nudge()
            stats.record_nudge()
            stats.record_nudge()
            summary = stats.get_summary_if_due()

        assert summary is not None
        assert summary["interval_nudges"] == 3
        assert summary["total_nudges"] == 3


@pytest.mark.unit
class TestControllerStatsFinalSummary:
    """Tests for shutdown final summary."""

    def test_final_summary_emitted(self) -> None:
        """emit_final_summary produces a controller.final_summary log."""
        stats = ControllerStats(startup_duration_s=9999.0)

        with patch("silvasonic.controller.controller_stats.log") as mock_log:
            stats.record_reconcile_cycle()
            stats.record_reconcile_cycle()
            stats.record_container_start("c1")
            stats.record_container_stop("c2")
            stats.record_reconcile_error()
            stats.record_nudge()
            stats.emit_final_summary()

        final_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "controller.final_summary"
        ]
        assert len(final_logs) == 1

        final = final_logs[0]
        assert final.kwargs["total_reconcile_cycles"] == 2
        assert final.kwargs["total_reconcile_errors"] == 1
        assert final.kwargs["total_containers_started"] == 1
        assert final.kwargs["total_containers_stopped"] == 1
        assert final.kwargs["total_nudges"] == 1
        assert "uptime_s" in final.kwargs
        assert "pending_cycles_since_last_summary" in final.kwargs


@pytest.mark.unit
class TestControllerStatsThreadSafety:
    """Basic thread-safety verification."""

    def test_concurrent_operations(self) -> None:
        """Multiple threads can record stats without error."""
        import threading

        stats = ControllerStats(startup_duration_s=0.0, summary_interval_s=9999.0)
        errors: list[Exception] = []

        def record_many(fn_name: str) -> None:
            try:
                for i in range(100):
                    if fn_name == "cycle":
                        stats.record_reconcile_cycle()
                    elif fn_name == "start":
                        stats.record_container_start(f"c{i}")
                    elif fn_name == "nudge":
                        stats.record_nudge()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=record_many, args=(op,)) for op in ("cycle", "start", "nudge")
        ]
        with patch("silvasonic.controller.controller_stats.log"):
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        assert len(errors) == 0, f"Exceptions occurred during concurrent execution: {errors}"
        # Assert the total counters track updates safely
        assert stats._total_reconcile_cycles == 100
        assert stats._total_containers_started == 100
        assert stats._total_nudges == 100
