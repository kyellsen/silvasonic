import pytest
from silvasonic.core.two_phase import TwoPhaseWindow


@pytest.mark.unit
class TestTwoPhaseWindow:
    def test_startup_phase_timing(self) -> None:
        """Test that the startup phase evaluates correctly based on time injected."""
        current_time = 100.0

        def fake_time() -> float:
            return current_time

        window = TwoPhaseWindow(
            startup_duration_s=10.0, summary_interval_s=5.0, time_func=fake_time
        )

        assert window.is_startup_phase is True
        assert window.consume_startup_transition() is False
        assert window.is_summary_due() is False
        assert window.uptime_s == 0.0

        current_time = 105.0  # Still in startup phase
        assert window.is_startup_phase is True
        assert window.consume_startup_transition() is False
        assert window.is_summary_due() is True  # 5 seconds elapsed, summary is due even in startup
        assert window.uptime_s == 5.0

        current_time = 110.1  # Startup phase exactly ended
        assert window.is_startup_phase is False
        # The transition should be consumed exactly once
        assert window.consume_startup_transition() is True
        assert window.consume_startup_transition() is False

    def test_summary_due_and_emission(self) -> None:
        """Test summary due logic and emission exactness."""
        current_time = 0.0

        def fake_time() -> float:
            return current_time

        window = TwoPhaseWindow(
            startup_duration_s=300.0, summary_interval_s=60.0, time_func=fake_time
        )

        # Advance time by 59 seconds
        current_time = 59.0
        assert window.is_summary_due() is False

        # Advance time by 1 more second to hit interval exactly
        current_time = 60.0
        assert window.is_summary_due() is True

        # Mark summary emitted
        elapsed = window.mark_summary_emitted()
        assert elapsed == 60.0
        assert window.is_summary_due() is False

        # Advance time by 61 seconds
        current_time = 121.0
        assert window.is_summary_due() is True

        elapsed2 = window.mark_summary_emitted()
        assert elapsed2 == 61.0
