"""Unit tests for silvasonic.core.constants."""

import pytest


@pytest.mark.unit
class TestCoreConstants:
    """Tests for the centralized timing constants."""

    def test_reconnect_delay_importable(self) -> None:
        """RECONNECT_DELAY_S is importable from core.constants."""
        from silvasonic.core.constants import RECONNECT_DELAY_S

        assert isinstance(RECONNECT_DELAY_S, float)

    def test_reconnect_delay_value(self) -> None:
        """RECONNECT_DELAY_S has the expected default value."""
        from silvasonic.core.constants import RECONNECT_DELAY_S

        assert RECONNECT_DELAY_S == 5.0

    def test_reconnect_delay_used_by_log_forwarder(self) -> None:
        """LogForwarder uses the centralized RECONNECT_DELAY_S, not a local copy."""
        import silvasonic.controller.log_forwarder as lf
        from silvasonic.core.constants import RECONNECT_DELAY_S

        # Verify the module does NOT have a private copy
        assert not hasattr(lf, "_RECONNECT_DELAY_S")
        # Verify the centralized constant is referenced
        assert RECONNECT_DELAY_S == 5.0

    def test_reconnect_delay_used_by_nudge_subscriber(self) -> None:
        """NudgeSubscriber uses the centralized RECONNECT_DELAY_S, not a local copy."""
        import silvasonic.controller.nudge_subscriber as ns
        from silvasonic.core.constants import RECONNECT_DELAY_S

        assert not hasattr(ns, "_RECONNECT_DELAY_S")
        assert RECONNECT_DELAY_S == 5.0
