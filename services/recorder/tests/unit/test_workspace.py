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

    def test_promotes_orphan_segments_from_buffer(self, tmp_path: Path) -> None:
        """Orphan WAVs in .buffer/ are promoted to data/ on startup."""
        from silvasonic.recorder.workspace import ensure_workspace

        # Simulate a previous crash: WAV files left in .buffer/
        for subdir in ("data/raw", "data/processed", ".buffer/raw", ".buffer/processed"):
            (tmp_path / subdir).mkdir(parents=True)

        orphan_raw = tmp_path / ".buffer" / "raw" / "orphan1.wav"
        orphan_proc = tmp_path / ".buffer" / "processed" / "orphan2.wav"
        orphan_raw.write_text("raw orphan")
        orphan_proc.write_text("processed orphan")

        ensure_workspace(tmp_path)

        # Orphans should be moved to data/
        assert not orphan_raw.exists()
        assert not orphan_proc.exists()
        assert (tmp_path / "data" / "raw" / "orphan1.wav").read_text() == "raw orphan"
        assert (tmp_path / "data" / "processed" / "orphan2.wav").read_text() == "processed orphan"
