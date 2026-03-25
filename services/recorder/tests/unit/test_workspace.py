"""Unit tests for silvasonic.recorder.workspace module."""

from pathlib import Path

import pytest


@pytest.mark.unit
class TestEnsureWorkspace:
    """Tests for ensure_workspace()."""

    def test_creates_all_directories(self, tmp_path: Path) -> None:
        """All four expected directories are created."""
        from silvasonic.recorder.workspace import ensure_workspace

        ensure_workspace(tmp_path)

        assert (tmp_path / "data" / "raw").is_dir()
        assert (tmp_path / "data" / "processed").is_dir()
        assert (tmp_path / ".buffer" / "raw").is_dir()
        assert (tmp_path / ".buffer" / "processed").is_dir()

    def test_idempotent(self, tmp_path: Path) -> None:
        """Calling twice does not raise or change existing dirs."""
        from silvasonic.recorder.workspace import ensure_workspace

        ensure_workspace(tmp_path)

        # Create a file inside to verify it persists
        marker = tmp_path / "data" / "raw" / "test.txt"
        marker.write_text("keep me")

        ensure_workspace(tmp_path)

        assert marker.read_text() == "keep me"

    def test_creates_nested_parents(self, tmp_path: Path) -> None:
        """Works with a nested base path that doesn't exist yet."""
        from silvasonic.recorder.workspace import ensure_workspace

        deep = tmp_path / "a" / "b" / "c"
        ensure_workspace(deep)

        assert (deep / "data" / "raw").is_dir()
        assert (deep / ".buffer" / "processed").is_dir()
