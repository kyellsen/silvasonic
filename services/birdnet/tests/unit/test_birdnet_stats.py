from __future__ import annotations

from unittest.mock import patch

import pytest
from silvasonic.birdnet.birdnet_stats import BirdnetStats


@pytest.mark.unit
class TestBirdnetStatsStartupPhase:
    def test_startup_logs_every_analyzed(self) -> None:
        stats = BirdnetStats(startup_duration_s=9999.0)

        with patch("silvasonic.birdnet.birdnet_stats.log") as mock_log:
            stats.record_analyzed(100, 5.5, 3)
            stats.record_analyzed(101, 2.1, 0)

        info_calls = [c for c in mock_log.info.call_args_list if c[0][0] == "birdnet.analyzed"]
        assert len(info_calls) == 2

        assert info_calls[0].kwargs["recording_id"] == 100
        assert info_calls[0].kwargs["duration_s"] == 5.5
        assert info_calls[0].kwargs["hits"] == 3

        assert info_calls[1].kwargs["recording_id"] == 101
        assert info_calls[1].kwargs["hits"] == 0

    def test_error_tracking(self) -> None:
        stats = BirdnetStats(startup_duration_s=9999.0)

        with patch("silvasonic.birdnet.birdnet_stats.log") as mock_log:
            stats.record_error(200, RuntimeError("model fail"))

        error_calls = [
            c for c in mock_log.error.call_args_list if c[0][0] == "birdnet.inference_error"
        ]
        assert len(error_calls) == 1
        assert error_calls[0].kwargs["recording_id"] == 200
        assert error_calls[0].kwargs["error"] == "model fail"
        assert stats.total_errors == 1


@pytest.mark.unit
class TestBirdnetStatsSteadyState:
    def _make_steady_state_stats(self, summary_interval_s: float = 300.0) -> BirdnetStats:
        return BirdnetStats(startup_duration_s=0.0, summary_interval_s=summary_interval_s)

    def test_steady_state_does_not_log_individual_analyzed(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=9999.0)

        with patch("silvasonic.birdnet.birdnet_stats.log") as mock_log:
            stats.record_analyzed(1, 1.0, 1)

        analyzed_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "birdnet.analyzed"]
        assert len(analyzed_logs) == 0

    def test_phase_transition_logged_once(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=9999.0)

        with patch("silvasonic.birdnet.birdnet_stats.log") as mock_log:
            stats.maybe_emit_summary()
            stats.maybe_emit_summary()

        transition_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "birdnet.startup_phase_complete"
        ]
        assert len(transition_logs) == 1

    def test_summary_emitted_after_interval(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.birdnet.birdnet_stats.log") as mock_log:
            stats.record_analyzed(1, 2.5, 4)
            stats.record_error(2, ValueError("bad audio"))
            stats.maybe_emit_summary()

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "birdnet.summary"]
        assert len(summary_logs) >= 1

        last = summary_logs[-1]
        assert last.kwargs["analyzed_recent"] == 1
        assert last.kwargs["hits_recent"] == 4
        assert last.kwargs["errors_recent"] == 1
        assert last.kwargs["total_analyzed"] == 1
        assert last.kwargs["total_hits"] == 4
        assert last.kwargs["total_errors"] == 1

    def test_summary_not_emitted_if_no_changes(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.birdnet.birdnet_stats.log"):
            stats.maybe_emit_summary()

        with patch("silvasonic.birdnet.birdnet_stats.log") as mock_log:
            stats.maybe_emit_summary()

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "birdnet.summary"]
        assert len(summary_logs) == 0

    def test_summary_resets_interval_counters(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.birdnet.birdnet_stats.log") as mock_log:
            stats.record_analyzed(1, 1.0, 2)
            stats.maybe_emit_summary()

            stats.record_analyzed(2, 1.0, 5)
            stats.record_analyzed(3, 1.0, 3)
            stats.maybe_emit_summary()

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "birdnet.summary"]
        assert len(summary_logs) >= 2

        last = summary_logs[-1]
        assert last.kwargs["analyzed_recent"] == 2
        assert last.kwargs["hits_recent"] == 8
        assert last.kwargs["total_analyzed"] == 3
        assert last.kwargs["total_hits"] == 10


@pytest.mark.unit
class TestBirdnetStatsFinalSummary:
    def test_final_summary_emitted(self) -> None:
        stats = BirdnetStats(startup_duration_s=9999.0)

        with patch("silvasonic.birdnet.birdnet_stats.log") as mock_log:
            stats.record_analyzed(1, 4.5, 2)
            stats.record_error(2, Exception("err"))
            stats.emit_final_summary()

        final_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "birdnet.shutdown"]
        assert len(final_logs) == 1

        final = final_logs[0]
        assert final.kwargs["total_analyzed"] == 1
        assert final.kwargs["total_hits"] == 2
        assert final.kwargs["total_errors"] == 1
        assert final.kwargs["total_duration_s"] == 4.5
