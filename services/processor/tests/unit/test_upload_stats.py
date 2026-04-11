"""Unit tests for UploadStats two-phase logging.

Follows the same test pattern as test_janitor_stats.py and test_indexer_stats.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from silvasonic.processor.modules.upload_stats import UploadStats


@pytest.mark.unit
class TestUploadStatsSteadyState:
    """Verify summary emission after the startup phase ends."""

    def _make_steady_state_stats(self, summary_interval_s: float = 300.0) -> UploadStats:
        return UploadStats(
            startup_duration_s=0.0,
            summary_interval_s=summary_interval_s,
        )

    def test_summary_emitted_after_startup_phase(self) -> None:
        """Summary log emitted with correct deltas once steady state starts."""
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        with patch("silvasonic.processor.modules.upload_stats.log") as mock_log:
            # record_attempt internally calls _maybe_emit_summary
            stats.record_attempt(True, 1024, "a.wav", "r/a.flac", 0.5)
            stats.record_attempt(False, 0, "b.wav", "r/b.flac", 1.0)

        summary_calls = [
            c for c in mock_log.info.call_args_list if c[0][0] == "upload_worker.summary"
        ]
        assert len(summary_calls) >= 1

        # Check totals across all summaries
        total_up = sum(c.kwargs["uploaded_recent"] for c in summary_calls)
        total_fail = sum(c.kwargs["failed_recent"] for c in summary_calls)
        assert total_up == 1
        assert total_fail == 1

    def test_summary_suppressed_when_nothing_happened(self) -> None:
        """No summary log if no uploads occurred since last summary."""
        stats = self._make_steady_state_stats(summary_interval_s=0.0)

        # Consume the first summary window (empty)
        with patch("silvasonic.processor.modules.upload_stats.log"):
            stats._maybe_emit_summary()

        # Second window — still nothing happened
        with patch("silvasonic.processor.modules.upload_stats.log") as mock_log:
            stats._maybe_emit_summary()

        summary_calls = [
            c for c in mock_log.info.call_args_list if c[0][0] == "upload_worker.summary"
        ]
        assert len(summary_calls) == 0

    def test_startup_transition_logged_once(self) -> None:
        """Startup-to-steady transition log emitted exactly once."""
        stats = self._make_steady_state_stats(summary_interval_s=9999.0)

        with patch("silvasonic.processor.modules.upload_stats.log") as mock_log:
            stats._maybe_emit_summary()
            stats._maybe_emit_summary()

        transition_logs = [
            c
            for c in mock_log.info.call_args_list
            if c[0][0] == "upload_worker.startup_phase_complete"
        ]
        assert len(transition_logs) == 1


@pytest.mark.unit
class TestUploadStatsFinalSummary:
    """Verify final shutdown summary includes lifetime totals."""

    def test_emit_final_summary_includes_lifetime_totals(self) -> None:
        """emit_final_summary includes total_uploaded, total_failed, MB."""
        stats = UploadStats(startup_duration_s=9999.0)

        with patch("silvasonic.processor.modules.upload_stats.log") as mock_log:
            stats.record_attempt(True, 2048, "a.wav", "r/a.flac", 0.5)
            stats.record_attempt(True, 4096, "b.wav", "r/b.flac", 0.3)
            stats.record_attempt(False, 0, "c.wav", "r/c.flac", 1.0)
            stats.emit_final_summary()

        final_logs = [
            c for c in mock_log.info.call_args_list if c[0][0] == "upload_worker.shutdown"
        ]
        assert len(final_logs) == 1

        final = final_logs[0]
        assert final.kwargs["total_uploaded"] == 2
        assert final.kwargs["total_failed"] == 1
        # 6144 bytes = 0.005859375 MB
        assert final.kwargs["total_mb_transferred"] == pytest.approx(0.01, abs=0.01)
