"""Unit tests for Recorder container spec: privileged mode (ADR-0007 §6).

With privileged=True, the Recorder has full /dev/snd access on all
Linux distributions without cross-distro GID resolution or SELinux
detection.  Podman rootless user namespaces are the security boundary.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from silvasonic.controller.container_spec import build_recorder_spec

# Minimal env dict for RecorderEnvConfig (via pydantic-settings)
_RECORDER_ENV = {
    "SILVASONIC_NETWORK": "test-net",
    "SILVASONIC_WORKSPACE_PATH": "/mnt/workspace",
    "SILVASONIC_REDIS_URL": "redis://test:6379/0",
}


def _make_device(**overrides: object) -> MagicMock:
    """Create a mock Device for build_recorder_spec."""
    device = MagicMock()
    device.name = overrides.pop("name", "0869-0389-00000000034F")
    device.config = {
        "alsa_device": "hw:2,0",
        "usb_serial": "00000000034F",
        **(overrides or {}),
    }
    return device


def _make_profile(**overrides: object) -> MagicMock:
    """Create a mock MicrophoneProfile for build_recorder_spec."""
    profile = MagicMock()
    profile.slug = overrides.pop("slug", "ultramic_384_evo")
    profile.config = overrides.pop(
        "config",
        {"audio": {"sample_rate": 384000, "channels": 1}},
    )
    return profile


@pytest.mark.unit
class TestBuildRecorderSpecPrivileged:
    """Verify Recorder spec uses privileged mode (KISS, ADR-0007 §6)."""

    @patch.dict("os.environ", _RECORDER_ENV)
    def test_spec_is_privileged(self) -> None:
        """Recorder runs privileged — Podman rootless is the sandbox."""
        spec = build_recorder_spec(_make_device(), _make_profile())

        assert spec.privileged is True

    @patch.dict("os.environ", _RECORDER_ENV)
    def test_spec_uses_symbolic_audio_group(self) -> None:
        """group_add uses symbolic 'audio' — works with privileged mode."""
        spec = build_recorder_spec(_make_device(), _make_profile())

        assert spec.group_add == ["audio"]

    @patch.dict("os.environ", _RECORDER_ENV)
    def test_spec_always_has_dev_snd(self) -> None:
        """Recorder spec always maps /dev/snd into the container."""
        spec = build_recorder_spec(_make_device(), _make_profile())

        assert "/dev/snd:/dev/snd" in spec.devices

    @patch.dict("os.environ", _RECORDER_ENV)
    def test_spec_has_no_security_opt(self) -> None:
        """No security_opt field needed with privileged mode."""
        spec = build_recorder_spec(_make_device(), _make_profile())
        # security_opt was removed from Tier2ServiceSpec (KISS refactoring)
        assert not hasattr(spec, "security_opt")
