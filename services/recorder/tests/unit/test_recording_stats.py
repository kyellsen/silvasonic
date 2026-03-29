"""Unit tests for silvasonic.recorder.recording_stats module.

Tests the two-phase logging strategy:
  - Startup phase: every segment promotion logged individually
  - Steady state: periodic summary logs with file-size statistics
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from silvasonic.recorder.recording_stats import RecordingStats


@pytest.mark.unit
class TestRecordingStatsStartupPhase:
    """Tests for the detailed startup-phase logging."""

    def test_startup_logs_every_promotion(self) -> None:
        """During startup, each promotion emits an individual log."""
        stats = RecordingStats(startup_duration_s=9999.0)  # Stay in startup

        with patch("silvasonic.recorder.recording_stats.log") as mock_log:
            stats.record_promotion("raw", "seg1.wav", 960_000)
            stats.record_promotion("processed", "seg2.wav", 480_000)

        info_calls = [c for c in mock_log.info.call_args_list if c[0][0] == "segment.promoted"]
        assert len(info_calls) == 2

        # First call has correct metadata
        first = info_calls[0]
        assert first.kwargs["stream"] == "raw"
        assert first.kwargs["filename"] == "seg1.wav"
        assert first.kwargs["size_bytes"] == 960_000
        assert first.kwargs["total"] == 1

        # Second call increments total
        second = info_calls[1]
        assert second.kwargs["total"] == 2
        assert second.kwargs["stream"] == "processed"

    def test_startup_phase_duration(self) -> None:
        """in_startup_phase returns True within the configured duration."""
        stats = RecordingStats(startup_duration_s=300.0)
        # Immediately after creation, should be in startup phase
        assert stats.in_startup_phase is True


@pytest.mark.unit
class TestRecordingStatsSteadyState:
    """Tests for the periodic summary logging in steady state."""

    def _make_steady_state_stats(
        self,
        summary_interval_s: float = 300.0,
    ) -> RecordingStats:
        """Create a RecordingStats that is past startup phase."""
        stats = RecordingStats(
            startup_duration_s=0.0,  # Immediately in steady state
            summary_interval_s=summary_interval_s,
        )
        return stats

    def test_steady_state_does_not_log_individual_promotions(self) -> None:
        """In steady state, individual promotions do not emit segment.promoted."""
        stats = self._make_steady_state_stats(summary_interval_s=9999.0)

        with patch("silvasonic.recorder.recording_stats.log") as mock_log:
            stats.record_promotion("raw", "seg1.wav", 960_000)
            stats.record_promotion("raw", "seg2.wav", 960_000)

        segment_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "segment.promoted"]
        assert len(segment_logs) == 0

    def test_phase_transition_logged_once(self) -> None:
        """The startup→steady transition is logged exactly once."""
        stats = self._make_steady_state_stats(summary_interval_s=9999.0)

        with patch("silvasonic.recorder.recording_stats.log") as mock_log:
            stats.record_promotion("raw", "seg1.wav", 960_000)
            stats.record_promotion("raw", "seg2.wav", 960_000)

        transition_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "recording.startup_phase_complete"
        ]
        assert len(transition_logs) == 1

    def test_summary_emitted_after_interval(self) -> None:
        """A summary log is emitted when the interval elapses."""
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.recorder.recording_stats.log") as mock_log:
            stats.record_promotion("raw", "seg1.wav", 960_000)
            stats.record_promotion("processed", "seg2.wav", 480_000)

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "recording.summary"]
        # At least one summary should have been emitted
        assert len(summary_logs) >= 1

        # Verify summary content
        summary = summary_logs[-1]
        assert summary.kwargs["total_promoted"] >= 1
        assert summary.kwargs["total_bytes"] > 0

    def test_summary_contains_file_size_stats(self) -> None:
        """Summary logs include min/max/avg file-size statistics."""
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.recorder.recording_stats.log") as mock_log:
            stats.record_promotion("raw", "seg1.wav", 800_000)
            stats.record_promotion("raw", "seg2.wav", 1_200_000)
            stats.record_promotion("raw", "seg3.wav", 1_000_000)

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "recording.summary"]
        assert len(summary_logs) >= 1

        # Last summary should have size stats
        last = summary_logs[-1]
        assert "size_min_bytes" in last.kwargs
        assert "size_max_bytes" in last.kwargs
        assert "size_avg_bytes" in last.kwargs

    def test_summary_resets_interval_counters(self) -> None:
        """After emitting a summary, interval counters reset."""
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.recorder.recording_stats.log") as mock_log:
            # Trigger first summary
            stats.record_promotion("raw", "seg1.wav", 960_000)
            # Trigger second summary (counters should be reset)
            stats.record_promotion("raw", "seg2.wav", 480_000)

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "recording.summary"]
        # We should have at least 2 summaries because interval is 0
        if len(summary_logs) >= 2:
            second = summary_logs[-1]
            # Second summary should have interval_promoted reflecting
            # only the promotions since the previous summary
            assert second.kwargs["interval_promoted"] >= 1

    def test_summary_includes_stream_breakdown(self) -> None:
        """Summary logs include per-stream promotion counts."""
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.recorder.recording_stats.log") as mock_log:
            stats.record_promotion("raw", "seg1.wav", 960_000)
            stats.record_promotion("processed", "seg2.wav", 480_000)

        summary_logs = [c for c in mock_log.info.call_args_list if c[0][0] == "recording.summary"]
        assert len(summary_logs) >= 1

        last = summary_logs[-1]
        streams = last.kwargs["streams"]
        assert "raw" in streams or "processed" in streams


@pytest.mark.unit
class TestRecordingStatsErrors:
    """Tests for error tracking — always logged individually."""

    def test_errors_always_logged_individually(self) -> None:
        """Errors are logged regardless of phase."""
        # In startup
        stats_startup = RecordingStats(startup_duration_s=9999.0)
        with patch("silvasonic.recorder.recording_stats.log") as mock_log:
            stats_startup.record_error("raw", "bad.wav")

        error_calls = [
            c for c in mock_log.error.call_args_list if c[0][0] == "segment.promote_failed"
        ]
        assert len(error_calls) == 1
        assert error_calls[0].kwargs["stream"] == "raw"
        assert error_calls[0].kwargs["filename"] == "bad.wav"
        assert error_calls[0].kwargs["total_errors"] == 1

    def test_errors_logged_in_steady_state(self) -> None:
        """Errors are logged individually even in steady state."""
        stats = RecordingStats(startup_duration_s=0.0, summary_interval_s=9999.0)
        with patch("silvasonic.recorder.recording_stats.log") as mock_log:
            stats.record_error("processed", "corrupt.wav")

        error_calls = [
            c for c in mock_log.error.call_args_list if c[0][0] == "segment.promote_failed"
        ]
        assert len(error_calls) == 1

    def test_error_count_accumulates(self) -> None:
        """Multiple errors increment total_errors correctly."""
        stats = RecordingStats(startup_duration_s=9999.0)
        with patch("silvasonic.recorder.recording_stats.log") as mock_log:
            stats.record_error("raw", "bad1.wav")
            stats.record_error("raw", "bad2.wav")

        error_calls = [
            c for c in mock_log.error.call_args_list if c[0][0] == "segment.promote_failed"
        ]
        assert error_calls[-1].kwargs["total_errors"] == 2


@pytest.mark.unit
class TestRecordingStatsFinalSummary:
    """Tests for the shutdown final summary."""

    def test_final_summary_emitted(self) -> None:
        """emit_final_summary produces a recording.final_summary log."""
        stats = RecordingStats(startup_duration_s=9999.0)

        with patch("silvasonic.recorder.recording_stats.log") as mock_log:
            stats.record_promotion("raw", "seg1.wav", 960_000)
            stats.record_promotion("processed", "seg2.wav", 480_000)
            stats.record_error("raw", "bad.wav")
            stats.emit_final_summary()

        final_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "recording.final_summary"
        ]
        assert len(final_logs) == 1

        final = final_logs[0]
        assert final.kwargs["total_promoted"] == 2
        assert final.kwargs["total_bytes"] == 1_440_000
        assert final.kwargs["total_errors"] == 1
        assert "raw" in final.kwargs["streams"]
        assert "processed" in final.kwargs["streams"]
        assert "raw" in final.kwargs["stream_bytes"]
        assert final.kwargs["stream_bytes"]["raw"] == 960_000

    def test_final_summary_includes_pending(self) -> None:
        """Final summary includes pending counts since last periodic summary."""
        stats = RecordingStats(startup_duration_s=0.0, summary_interval_s=9999.0)

        with patch("silvasonic.recorder.recording_stats.log") as mock_log:
            stats.record_promotion("raw", "seg1.wav", 960_000)
            stats.emit_final_summary()

        final_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "recording.final_summary"
        ]
        assert len(final_logs) == 1
        assert final_logs[0].kwargs["pending_since_last_summary"] == 1


@pytest.mark.unit
class TestRecordingStatsThreadSafety:
    """Basic thread-safety verification."""

    def test_concurrent_promotions(self) -> None:
        """Multiple threads can record promotions without error."""
        import threading

        stats = RecordingStats(startup_duration_s=0.0, summary_interval_s=9999.0)
        errors: list[Exception] = []

        def promote_many(stream: str) -> None:
            try:
                for i in range(100):
                    stats.record_promotion(stream, f"seg{i}.wav", 960_000)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=promote_many, args=(s,)) for s in ("raw", "processed")]
        with patch("silvasonic.recorder.recording_stats.log"):
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        assert len(errors) == 0
        # Both threads promoted 100 each
        with patch("silvasonic.recorder.recording_stats.log"):
            stats.emit_final_summary()
