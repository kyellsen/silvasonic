"""Unit tests for Janitor — Data retention & storage management.

Covers:
- Retention mode evaluation (idle/housekeeping/defensive/panic)
- Deletion criteria per mode (with and without Cloud-Sync-Fallback)
- Soft delete pattern (physical file removal + DB flag update)
- Panic filesystem fallback (mtime-based blind cleanup)
- Batch size enforcement
- Heartbeat metrics reporting
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.core.schemas.system_config import ProcessorSettings
from silvasonic.processor.janitor import (
    RetentionMode,
    delete_files,
    evaluate_mode,
    get_disk_usage,
    panic_filesystem_fallback,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Mode Evaluation
# ---------------------------------------------------------------------------


class TestEvaluateMode:
    """Tests for evaluate_mode() threshold logic."""

    def test_idle_below_all_thresholds(self) -> None:
        """60% usage → mode idle, no deletions needed."""
        settings = ProcessorSettings()
        assert evaluate_mode(60.0, settings) == RetentionMode.IDLE

    def test_housekeeping_mode_triggers(self) -> None:
        """75% usage → mode housekeeping."""
        settings = ProcessorSettings()
        assert evaluate_mode(75.0, settings) == RetentionMode.HOUSEKEEPING

    def test_defensive_mode_triggers(self) -> None:
        """85% usage → mode defensive."""
        settings = ProcessorSettings()
        assert evaluate_mode(85.0, settings) == RetentionMode.DEFENSIVE

    def test_panic_mode_triggers(self) -> None:
        """95% usage → mode panic."""
        settings = ProcessorSettings()
        assert evaluate_mode(95.0, settings) == RetentionMode.PANIC

    def test_exact_threshold_warning(self) -> None:
        """Exactly 70.0% → housekeeping (inclusive)."""
        settings = ProcessorSettings()
        assert evaluate_mode(70.0, settings) == RetentionMode.HOUSEKEEPING

    def test_exact_threshold_critical(self) -> None:
        """Exactly 80.0% → defensive (inclusive)."""
        settings = ProcessorSettings()
        assert evaluate_mode(80.0, settings) == RetentionMode.DEFENSIVE

    def test_exact_threshold_emergency(self) -> None:
        """Exactly 90.0% → panic (inclusive)."""
        settings = ProcessorSettings()
        assert evaluate_mode(90.0, settings) == RetentionMode.PANIC


# ---------------------------------------------------------------------------
# Disk Usage
# ---------------------------------------------------------------------------


class TestGetDiskUsage:
    """Tests for get_disk_usage()."""

    async def test_returns_percentage(self, tmp_path: Path) -> None:
        """get_disk_usage returns a float percentage."""
        pct = await get_disk_usage(tmp_path)
        assert isinstance(pct, float)
        assert 0.0 <= pct <= 100.0


# ---------------------------------------------------------------------------
# File Deletion
# ---------------------------------------------------------------------------


class TestDeleteFiles:
    """Tests for delete_files() physical removal."""

    async def test_deletes_existing_files(self, tmp_path: Path) -> None:
        """Both raw and processed WAV files are deleted."""
        raw = tmp_path / "sensor" / "data" / "raw" / "test.wav"
        proc = tmp_path / "sensor" / "data" / "processed" / "test.wav"
        raw.parent.mkdir(parents=True)
        proc.parent.mkdir(parents=True)
        raw.write_bytes(b"\x00" * 100)
        proc.write_bytes(b"\x00" * 100)

        removed = await delete_files(
            tmp_path, "sensor/data/raw/test.wav", "sensor/data/processed/test.wav"
        )
        assert removed == 2
        assert not raw.exists()
        assert not proc.exists()

    async def test_missing_file_no_error(self, tmp_path: Path) -> None:
        """Non-existing files are gracefully skipped."""
        removed = await delete_files(tmp_path, "nonexistent/raw.wav", "nonexistent/proc.wav")
        assert removed == 0


class TestDeleteWorkerClips:
    """Tests for delete_worker_clips()."""

    async def test_deletes_physical_files_and_updates_db(self, tmp_path: Path) -> None:
        """Queried files are unlinked and DB is updated."""
        from silvasonic.processor.janitor import delete_worker_clips

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("birdnet", "clips/123.wav")]
        session.execute.return_value = mock_result

        # Create the file physically
        clip_path = tmp_path / "birdnet" / "clips" / "123.wav"
        clip_path.parent.mkdir(parents=True)
        clip_path.write_bytes(b"\x00")
        assert clip_path.exists()

        removed = await delete_worker_clips(session, 10, tmp_path)
        assert removed == 1
        assert not clip_path.exists()

        # Check DB update was called
        assert session.execute.call_count == 2
        update_call = session.execute.call_args_list[1]
        assert "UPDATE detections" in str(update_call[0][0])
        assert update_call[0][1] == {"id": 10, "clip_paths": ["clips/123.wav"]}

    async def test_missing_files_are_graceful(self, tmp_path: Path) -> None:
        """Missing physical files do not crash the cleanup."""
        from silvasonic.processor.janitor import delete_worker_clips

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("birdnet", "clips/missing.wav")]
        session.execute.return_value = mock_result

        # Do NOT create the file physically

        removed = await delete_worker_clips(session, 10, tmp_path)
        assert removed == 1

        # DB update is still called because DB rows existed and missing files
        # are considered successfully removed
        assert session.execute.call_count == 2
        update_call = session.execute.call_args_list[1]
        assert update_call[0][1] == {"id": 10, "clip_paths": ["clips/missing.wav"]}


# ---------------------------------------------------------------------------
# Panic Filesystem Fallback
# ---------------------------------------------------------------------------


class TestPanicFilesystemFallback:
    """Tests for panic_filesystem_fallback() mtime-based cleanup."""

    async def test_deletes_oldest_first(self, tmp_path: Path) -> None:
        """Oldest files (by mtime) are deleted first."""
        sensor_dir = tmp_path / "sensor" / "data" / "processed"
        sensor_dir.mkdir(parents=True)

        # Create 3 files with different mtimes
        for i, name in enumerate(["old.wav", "mid.wav", "new.wav"]):
            f = sensor_dir / name
            f.write_bytes(b"\x00" * 100)
            os.utime(f, (1000 + i * 100, 1000 + i * 100))

        deleted = await panic_filesystem_fallback(tmp_path, batch_size=2)
        assert deleted == 2
        # Only newest should remain
        remaining = list(sensor_dir.glob("*.wav"))
        assert len(remaining) == 1
        assert remaining[0].name == "new.wav"

    async def test_batch_size_limits_deletion(self, tmp_path: Path) -> None:
        """Batch size limits the number of files deleted."""
        sensor_dir = tmp_path / "sensor" / "data" / "raw"
        sensor_dir.mkdir(parents=True)

        for i in range(10):
            (sensor_dir / f"file_{i:02d}.wav").write_bytes(b"\x00" * 100)

        deleted = await panic_filesystem_fallback(tmp_path, batch_size=3)
        assert deleted == 3
        remaining = list(sensor_dir.glob("*.wav"))
        assert len(remaining) == 7

    async def test_empty_workspace_returns_zero(self, tmp_path: Path) -> None:
        """Empty workspace → 0 files deleted, no crash."""
        deleted = await panic_filesystem_fallback(tmp_path, batch_size=50)
        assert deleted == 0

    async def test_getmtime_oserror_skips_file(self, tmp_path: Path) -> None:
        """OSError during getmtime (race condition) gracefully skips the file."""
        sensor_dir = tmp_path / "sensor" / "data" / "processed"
        sensor_dir.mkdir(parents=True)
        f = sensor_dir / "vanished.wav"
        f.write_bytes(b"\x00" * 100)

        with patch("os.path.getmtime", side_effect=OSError("File vanished")):
            deleted = await panic_filesystem_fallback(tmp_path, batch_size=10)

        assert deleted == 0

    async def test_unlink_oserror_logged(self, tmp_path: Path) -> None:
        """OSError during unlink is caught and logged, file not counted."""
        sensor_dir = tmp_path / "sensor" / "data" / "processed"
        sensor_dir.mkdir(parents=True)
        f = sensor_dir / "locked.wav"
        f.write_bytes(b"\x00" * 100)

        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            deleted = await panic_filesystem_fallback(tmp_path, batch_size=10)

        assert deleted == 0


# ---------------------------------------------------------------------------
# run_cleanup_safe (DB-failure wrapper)
# ---------------------------------------------------------------------------


class TestRunCleanupSafe:
    """Tests for run_cleanup_safe() — the top-level entry point with DB-failure protection."""

    async def test_idle_returns_immediately(self) -> None:
        """Below all thresholds → idle result, no session created."""
        from silvasonic.processor.janitor import run_cleanup_safe

        settings = ProcessorSettings()
        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=50.0):
            result = await run_cleanup_safe(Path("/data"), settings)

        assert result.mode == RetentionMode.IDLE
        assert result.files_deleted == 0

    async def test_normal_flow_delegates_to_run_cleanup(self) -> None:
        """Above threshold + DB available → delegates to run_cleanup."""
        from silvasonic.processor.janitor import run_cleanup_safe

        settings = ProcessorSettings()
        mock_session = AsyncMock()
        mock_result_cloud_sync = MagicMock()
        mock_result_cloud_sync.fetchone.return_value = None
        mock_result_find = MagicMock()
        mock_result_find.fetchall.return_value = []
        mock_session.execute.side_effect = [mock_result_cloud_sync, mock_result_find]

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0),
            patch("silvasonic.core.database.session.get_session", return_value=mock_ctx),
        ):
            result = await run_cleanup_safe(Path("/data"), settings)

        assert result.mode == RetentionMode.HOUSEKEEPING
        assert result.files_deleted == 0

    async def test_db_failure_in_panic_triggers_filesystem_fallback(
        self,
        tmp_path: Path,
    ) -> None:
        """DB failure during Panic → falls back to mtime-based filesystem cleanup."""
        from silvasonic.processor.janitor import run_cleanup_safe

        settings = ProcessorSettings()

        # Create WAV files to delete
        sensor_dir = tmp_path / "mic" / "data" / "processed"
        sensor_dir.mkdir(parents=True)
        (sensor_dir / "old.wav").write_bytes(b"\x00" * 100)

        with (
            patch("silvasonic.processor.janitor.get_disk_usage", return_value=95.0),
            patch(
                "silvasonic.core.database.session.get_session",
                side_effect=ConnectionError("DB unreachable"),
            ),
        ):
            result = await run_cleanup_safe(tmp_path, settings)

        assert result.mode == RetentionMode.PANIC
        assert result.files_deleted == 1
        assert not (sensor_dir / "old.wav").exists()

    async def test_db_failure_in_housekeeping_skips_safely(self) -> None:
        """DB failure during Housekeeping → skips cycle, no data loss."""
        from silvasonic.processor.janitor import run_cleanup_safe

        settings = ProcessorSettings()

        with (
            patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0),
            patch(
                "silvasonic.core.database.session.get_session",
                side_effect=ConnectionError("DB unreachable"),
            ),
        ):
            result = await run_cleanup_safe(Path("/data"), settings)

        assert result.mode == RetentionMode.HOUSEKEEPING
        assert result.files_deleted == 0

    async def test_db_failure_in_defensive_skips_safely(self) -> None:
        """DB failure during Defensive → skips cycle, no data loss."""
        from silvasonic.processor.janitor import run_cleanup_safe

        settings = ProcessorSettings()

        with (
            patch("silvasonic.processor.janitor.get_disk_usage", return_value=85.0),
            patch(
                "silvasonic.core.database.session.get_session",
                side_effect=ConnectionError("DB unreachable"),
            ),
        ):
            result = await run_cleanup_safe(Path("/data"), settings)

        assert result.mode == RetentionMode.DEFENSIVE
        assert result.files_deleted == 0
