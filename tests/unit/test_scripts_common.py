"""Unit tests for scripts/common.py — cross-distro group membership checks.

Verifies the 3-state logic (exists, is_in_db, is_active) that setup.py
uses to determine whether the host user has the required groups (audio,
dialout) configured correctly.  All OS-level calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from common import check_group_membership, group_exists

# ── group_exists ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestGroupExists:
    """Verify group_exists() correctly queries /etc/group via grp module."""

    def test_existing_group_returns_true(self) -> None:
        """A group that exists in /etc/group returns True."""
        mock_entry = MagicMock()
        mock_entry.gr_gid = 29
        with patch("common.grp.getgrnam", return_value=mock_entry):
            assert group_exists("audio") is True

    def test_missing_group_returns_false(self) -> None:
        """A group not in /etc/group (e.g. 'gpio' on Fedora) returns False."""
        with patch("common.grp.getgrnam", side_effect=KeyError("gpio")):
            assert group_exists("gpio") is False


# ── check_group_membership ────────────────────────────────────────────────────


@pytest.mark.unit
class TestCheckGroupMembership:
    """Verify the 3-state group membership check for cross-distro robustness."""

    def test_nonexistent_group_returns_triple_false(self) -> None:
        """If the group doesn't exist on this distro, all three states are False."""
        with patch("common.group_exists", return_value=False):
            exists, in_db, active = check_group_membership("gpio", "testuser")

        assert exists is False
        assert in_db is False
        assert active is False

    def test_user_active_in_group(self) -> None:
        """User is in the group AND it's active in the current shell session."""
        audio_gid = 29
        mock_grp_audio = MagicMock(gr_gid=audio_gid, gr_name="audio", gr_mem=["testuser"])
        mock_grp_primary = MagicMock(gr_gid=1000, gr_name="testuser")

        with (
            patch("common.group_exists", return_value=True),
            patch("common.os.getgroups", return_value=[1000, audio_gid]),
            patch(
                "common.grp.getgrgid",
                side_effect=lambda gid: {
                    1000: mock_grp_primary,
                    audio_gid: mock_grp_audio,
                }[gid],
            ),
            patch("common.grp.getgrall", return_value=[mock_grp_audio]),
            patch("common.pwd.getpwnam", return_value=MagicMock(pw_gid=1000)),
        ):
            exists, in_db, active = check_group_membership("audio", "testuser")

        assert exists is True
        assert in_db is True
        assert active is True

    def test_user_in_db_but_not_active(self) -> None:
        """User added to group in /etc/group but hasn't re-logged (needs reboot)."""
        audio_gid = 29
        mock_grp_audio = MagicMock(gr_gid=audio_gid, gr_name="audio", gr_mem=["testuser"])
        mock_grp_primary = MagicMock(gr_gid=1000, gr_name="testuser")

        with (
            patch("common.group_exists", return_value=True),
            # Current shell session does NOT have audio group
            patch("common.os.getgroups", return_value=[1000]),
            patch("common.grp.getgrgid", return_value=mock_grp_primary),
            patch("common.grp.getgrall", return_value=[mock_grp_audio]),
            patch("common.pwd.getpwnam", return_value=MagicMock(pw_gid=1000)),
        ):
            exists, in_db, active = check_group_membership("audio", "testuser")

        assert exists is True
        assert in_db is True
        assert active is False

    def test_user_not_in_group_at_all(self) -> None:
        """Group exists but user is not a member anywhere."""
        audio_gid = 29
        # audio group exists but "testuser" is not in gr_mem
        mock_grp_audio = MagicMock(gr_gid=audio_gid, gr_name="audio", gr_mem=["otheruser"])
        mock_grp_primary = MagicMock(gr_gid=1000, gr_name="testuser")

        with (
            patch("common.group_exists", return_value=True),
            patch("common.os.getgroups", return_value=[1000]),
            patch("common.grp.getgrgid", return_value=mock_grp_primary),
            patch("common.grp.getgrall", return_value=[mock_grp_audio]),
            patch("common.pwd.getpwnam", return_value=MagicMock(pw_gid=1000)),
        ):
            exists, in_db, active = check_group_membership("audio", "testuser")

        assert exists is True
        assert in_db is False
        assert active is False

    def test_user_defaults_to_env_user(self) -> None:
        """When user=None, falls back to $USER environment variable."""
        with (
            patch("common.group_exists", return_value=False),
            patch.dict("os.environ", {"USER": "pi"}),
        ):
            exists, _, _ = check_group_membership("gpio")

        # group_exists returns False, so we short-circuit — the important
        # thing is that it didn't crash when user was None
        assert exists is False
