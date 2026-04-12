from __future__ import annotations

from unittest.mock import patch

import pytest
from silvasonic.processor.modules.indexer_stats import IndexerStats


@pytest.mark.unit
class TestIndexerStatsStartupPhase:
    def test_startup_logs_every_indexed(self) -> None:
        stats = IndexerStats(startup_duration_s=9999.0)

        with patch("silvasonic.processor.modules.indexer_stats.log") as mock_log:
            stats.record_indexed("file1.wav", "sensor_A", 1.5)
            stats.record_indexed("file2.wav", "sensor_B", 2.0)

        info_calls = [c for c in mock_log.info.call_args_list if c[0][0] == "indexer.indexed"]
        assert len(info_calls) == 2

        assert info_calls[0].kwargs["file"] == "file1.wav"
        assert info_calls[0].kwargs["sensor_id"] == "sensor_A"
        assert info_calls[0].kwargs["duration"] == 1.5

        assert info_calls[1].kwargs["file"] == "file2.wav"

    def test_error_tracking(self) -> None:
        stats = IndexerStats(startup_duration_s=9999.0)

        with patch("silvasonic.processor.modules.indexer_stats.log") as mock_log:
            stats.record_error("bad.wav")

        error_calls = [c for c in mock_log.exception.call_args_list if c[0][0] == "indexer.error"]
        assert len(error_calls) == 1
        assert error_calls[0].kwargs["file"] == "bad.wav"
        assert stats.total_errors == 1

    def test_skipped_tracking(self) -> None:
        stats = IndexerStats(startup_duration_s=9999.0)
        stats.record_skipped()
        stats.record_skipped()
        assert stats.total_skipped == 2


@pytest.mark.unit
class TestIndexerStatsSteadyState:
    def _make_steady_state_stats(self, summary_interval_s: float = 300.0) -> IndexerStats:
        return IndexerStats(startup_duration_s=0.0, summary_interval_s=summary_interval_s)

    def test_steady_state_does_not_log_individual_indexed(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=9999.0)

        with patch("silvasonic.processor.modules.indexer_stats.log") as mock_log:
            stats.record_indexed("file1.wav", "sensor", 1.0)
            stats.record_indexed("file2.wav", "sensor", 1.0)

        indexed_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "indexer.indexed"]
        assert len(indexed_logs) == 0

    def test_phase_transition_logged_once(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=9999.0)

        with patch("silvasonic.processor.modules.indexer_stats.log") as mock_log:
            stats.maybe_emit_summary()
            stats.maybe_emit_summary()

        transition_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "indexer.startup_phase_complete"
        ]
        assert len(transition_logs) == 1

    def test_summary_emitted_after_interval(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.processor.modules.indexer_stats.log") as mock_log:
            stats.record_indexed("file1.wav", "sensor", 1.0)
            stats.record_error("file2.wav")
            stats.maybe_emit_summary()

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "indexer.summary"]
        assert len(summary_logs) >= 1

        last = summary_logs[-1]
        assert last.kwargs["indexed_recent"] == 1
        assert last.kwargs["errors_recent"] == 1
        assert last.kwargs["total_indexed"] == 1

    def test_summary_not_emitted_if_no_changes(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        # Trigger phase transition log first
        with patch("silvasonic.processor.modules.indexer_stats.log"):
            stats.maybe_emit_summary()

        with patch("silvasonic.processor.modules.indexer_stats.log") as mock_log:
            stats.maybe_emit_summary()

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "indexer.summary"]
        assert len(summary_logs) == 0

    def test_summary_resets_interval_counters(self) -> None:
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.processor.modules.indexer_stats.log") as mock_log:
            stats.record_indexed("1.wav", "sensor", 1.0)
            stats.maybe_emit_summary()

            stats.record_indexed("2.wav", "sensor", 1.0)
            stats.record_indexed("3.wav", "sensor", 1.0)
            stats.maybe_emit_summary()

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "indexer.summary"]
        assert len(summary_logs) >= 2

        last = summary_logs[-1]
        assert last.kwargs["indexed_recent"] == 2
        assert last.kwargs["total_indexed"] == 3


@pytest.mark.unit
class TestIndexerStatsFinalSummary:
    def test_final_summary_emitted(self) -> None:
        stats = IndexerStats(startup_duration_s=9999.0)

        with patch("silvasonic.processor.modules.indexer_stats.log") as mock_log:
            stats.record_indexed("f.wav", "s", 1.0)
            stats.record_error("bad.wav")
            stats.record_skipped()
            stats.emit_final_summary()

        final_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "indexer.shutdown"]
        assert len(final_logs) == 1

        final = final_logs[0]
        assert final.kwargs["total_indexed"] == 1
        assert final.kwargs["total_errors"] == 1
        assert final.kwargs["total_skipped"] == 1
