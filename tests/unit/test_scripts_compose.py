"""Unit tests for scripts/compose.py — the podman-compose wrapper."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from compose import TIER1_OOM_SCORE_ADJ, compose


@pytest.mark.unit
class TestTier1OomPriority:
    """Every container compose starts gets the Tier 1 OOM score (ADR-0020)."""

    def test_oom_score_passed_to_podman(self) -> None:
        """podman-compose ignores the compose key, so the score goes in as a run argument."""
        with (
            patch("compose.shutil.which", return_value="/usr/bin/podman-compose"),
            patch("compose.load_env_value", return_value=None),
            patch("compose.run_command") as run,
        ):
            compose("up", "-d")

        cmd = run.call_args.args[0]
        assert cmd[0] == "podman-compose"
        assert f"--podman-run-args=--oom-score-adj={TIER1_OOM_SCORE_ADJ}" in cmd
        # Global options precede the subcommand
        assert cmd.index("up") > cmd.index("-f")
        assert cmd[-2:] == ["up", "-d"]

    def test_tier1_sits_between_recorder_and_workers(self) -> None:
        """Above the Recorder's rootless floor (0 or 200), below the workers' 500."""
        assert 200 < TIER1_OOM_SCORE_ADJ < 500
