"""Unit tests for ControllerSettings — configuration contract tests.

Verifies that ControllerSettings (Pydantic BaseSettings) provides
correct defaults and respects SILVASONIC_* environment variable overrides.
These are pure contract tests against the settings model, not the service.
"""

from unittest.mock import patch

import pytest
from silvasonic.controller.settings import ControllerSettings


@pytest.mark.unit
class TestControllerSettingsDefaults:
    """Verify production-relevant defaults are set correctly."""

    def test_controller_port_default(self) -> None:
        """CONTROLLER_PORT defaults to 9100."""
        cfg = ControllerSettings()
        assert cfg.CONTROLLER_PORT == 9100

    def test_monitor_poll_interval_default(self) -> None:
        """CONTROLLER_MONITOR_POLL_INTERVAL_S defaults to 10.0."""
        cfg = ControllerSettings()
        assert cfg.CONTROLLER_MONITOR_POLL_INTERVAL_S == 10.0

    def test_log_forwarder_poll_interval_default(self) -> None:
        """LOG_FORWARDER_POLL_INTERVAL_S defaults to 1.0."""
        cfg = ControllerSettings()
        assert cfg.LOG_FORWARDER_POLL_INTERVAL_S == 1.0

    def test_reconcile_interval_default(self) -> None:
        """RECONCILE_INTERVAL_S defaults to 1.0."""
        cfg = ControllerSettings()
        assert cfg.RECONCILE_INTERVAL_S == 1.0

    def test_device_offline_grace_period_default(self) -> None:
        """DEVICE_OFFLINE_GRACE_PERIOD_S defaults to 3.0."""
        cfg = ControllerSettings()
        assert cfg.DEVICE_OFFLINE_GRACE_PERIOD_S == 3.0


@pytest.mark.unit
class TestControllerSettingsEnvOverride:
    """Verify SILVASONIC_* env vars override defaults."""

    def test_controller_port_env_override(self) -> None:
        """CONTROLLER_PORT respects env override."""
        with patch.dict("os.environ", {"SILVASONIC_CONTROLLER_PORT": "7777"}):
            cfg = ControllerSettings()
            assert cfg.CONTROLLER_PORT == 7777

    def test_monitor_poll_interval_env_override(self) -> None:
        """CONTROLLER_MONITOR_POLL_INTERVAL_S respects env override."""
        with patch.dict("os.environ", {"SILVASONIC_CONTROLLER_MONITOR_POLL_INTERVAL_S": "30.0"}):
            cfg = ControllerSettings()
            assert cfg.CONTROLLER_MONITOR_POLL_INTERVAL_S == 30.0

    def test_log_forwarder_poll_interval_env_override(self) -> None:
        """LOG_FORWARDER_POLL_INTERVAL_S respects env override."""
        with patch.dict("os.environ", {"SILVASONIC_LOG_FORWARDER_POLL_INTERVAL_S": "5.0"}):
            cfg = ControllerSettings()
            assert cfg.LOG_FORWARDER_POLL_INTERVAL_S == 5.0

    def test_reconcile_interval_env_override(self) -> None:
        """RECONCILE_INTERVAL_S respects env override."""
        with patch.dict("os.environ", {"SILVASONIC_RECONCILE_INTERVAL_S": "0.5"}):
            cfg = ControllerSettings()
            assert cfg.RECONCILE_INTERVAL_S == 0.5

    def test_device_offline_grace_period_env_override(self) -> None:
        """DEVICE_OFFLINE_GRACE_PERIOD_S respects env override."""
        with patch.dict("os.environ", {"SILVASONIC_DEVICE_OFFLINE_GRACE_PERIOD_S": "10.0"}):
            cfg = ControllerSettings()
            assert cfg.DEVICE_OFFLINE_GRACE_PERIOD_S == 10.0
