from __future__ import annotations

from unittest.mock import patch

import pytest
from silvasonic.processor.modules.janitor_stats import JanitorStats


@pytest.mark.unit
class TestJanitorStatsStartupPhase:
    def test_startup_logs_every_deleted(self) -> None:
        stats = JanitorStats(startup_duration_s=9999.0)

        with patch("silvasonic.processor.modules.janitor_stats.log") as mock_log:
            stats.record_deleted(100, "proc1.wav", "housekeeping", False)
            stats.record_deleted(101, None, "defensive", True)

        info_calls = [c for c in mock_log.info.call_args_list if c[0][0] == "janitor.deleted"]
        assert len(info_calls) == 2

        assert info_calls[0].kwargs["recording_id"] == 100
        assert info_calls[0].kwargs["mode"] == "housekeeping"
        assert info_calls[0].kwargs["cloud_sync_fallback"] is False

        assert info_calls[1].kwargs["recording_id"] == 101
        assert info_calls[1].kwargs["file_processed"] is None
        assert info_calls[1].kwargs["cloud_sync_fallback"] is True

    def test_error_tracking(self) -> None:
        stats = JanitorStats(startup_duration_s=9999.0)

        with patch("silvasonic.processor.modules.janitor_stats.log") as mock_log:
            stats.record_error(200, "proc.wav")

        error_calls = [
            c for c in mock_log.exception.call_args_list if c[0][0] == "janitor.delete_error"
        ]
        assert len(error_calls) == 1
        assert error_calls[0].kwargs["recording_id"] == 200
        assert error_calls[0].kwargs["file_processed"] == "proc.wav"
        assert stats.total_errors == 1


@pytest.mark.unit
class TestJanitorStatsSteadyState:
    def _make_steady_state_stats(self, summary_interval_s: float = 300.0) -> JanitorStats:
        return JanitorStats(startup_duration_s=0.0, summary_interval_s=summary_interval_s)

    def test_steady_state_does_not_log_individual_deleted(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=9999.0)

        with patch("silvasonic.processor.modules.janitor_stats.log") as mock_log:
            stats.record_deleted(1, "f.wav", "housekeeping", False)

        deleted_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "janitor.deleted"]
        assert len(deleted_logs) == 0

    def test_phase_transition_logged_once(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=9999.0)

        with patch("silvasonic.processor.modules.janitor_stats.log") as mock_log:
            stats.maybe_emit_summary("housekeeping", 50.0, False)
            stats.maybe_emit_summary("housekeeping", 50.0, False)

        transition_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "janitor.startup_phase_complete"
        ]
        assert len(transition_logs) == 1

    def test_summary_emitted_after_interval(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.processor.modules.janitor_stats.log") as mock_log:
            stats.record_deleted(1, "f.wav", "housekeeping", False)
            stats.record_error(2, "f2.wav")
            stats.maybe_emit_summary("defensive", 85.5, True)

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "janitor.summary"]
        assert len(summary_logs) >= 1

        last = summary_logs[-1]
        assert last.kwargs["mode"] == "defensive"
        assert last.kwargs["disk_usage_percent"] == 85.5
        assert last.kwargs["deleted_recent"] == 1
        assert last.kwargs["errors_recent"] == 1
        assert last.kwargs["total_deleted"] == 1
        assert last.kwargs["cloud_sync_fallback"] is True

    def test_summary_not_emitted_if_no_changes(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.processor.modules.janitor_stats.log"):
            stats.maybe_emit_summary("housekeeping", 50.0, False)

        with patch("silvasonic.processor.modules.janitor_stats.log") as mock_log:
            stats.maybe_emit_summary("housekeeping", 50.0, False)

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "janitor.summary"]
        assert len(summary_logs) == 0

    def test_summary_resets_interval_counters(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.processor.modules.janitor_stats.log") as mock_log:
            stats.record_deleted(1, "f.wav", "housekeeping", False)
            stats.maybe_emit_summary("housekeeping", 50.0, False)

            stats.record_deleted(2, "f2.wav", "housekeeping", False)
            stats.record_deleted(3, "f3.wav", "housekeeping", False)
            stats.maybe_emit_summary("housekeeping", 50.0, False)

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "janitor.summary"]
        assert len(summary_logs) >= 2

        last = summary_logs[-1]
        assert last.kwargs["deleted_recent"] == 2
        assert last.kwargs["total_deleted"] == 3


@pytest.mark.unit
class TestJanitorStatsFinalSummary:
    def test_final_summary_emitted(self) -> None:
        stats = JanitorStats(startup_duration_s=9999.0)

        with patch("silvasonic.processor.modules.janitor_stats.log") as mock_log:
            stats.record_deleted(1, "f.wav", "h", False)
            stats.record_error(2, "f2.wav")
            stats.emit_final_summary()

        final_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "janitor.shutdown"]
        assert len(final_logs) == 1

        final = final_logs[0]
        assert final.kwargs["total_deleted"] == 1
        assert final.kwargs["total_errors"] == 1
