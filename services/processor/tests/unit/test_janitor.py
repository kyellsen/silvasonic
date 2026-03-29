"""Unit tests for Janitor — Data retention & storage management.

Covers:
- Retention mode evaluation (idle/housekeeping/defensive/panic)
- Deletion criteria per mode (with and without Uploader-Fallback)
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
from silvasonic.core.config_schemas import ProcessorSettings
from silvasonic.processor.janitor import (
    JanitorResult,
    RetentionMode,
    delete_files,
    evaluate_mode,
    find_deletable,
    get_disk_usage,
    has_uploader_configured,
    panic_filesystem_fallback,
    run_cleanup,
    soft_delete,
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

    def test_returns_percentage(self, tmp_path: Path) -> None:
        """get_disk_usage returns a float percentage."""
        pct = get_disk_usage(tmp_path)
        assert isinstance(pct, float)
        assert 0.0 <= pct <= 100.0


# ---------------------------------------------------------------------------
# Uploader Fallback Detection
# ---------------------------------------------------------------------------


class TestHasUploaderConfigured:
    """Tests for has_uploader_configured()."""

    async def test_no_storage_remotes_returns_false(self) -> None:
        """No active storage_remotes → returns False."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        assert await has_uploader_configured(mock_session) is False

    async def test_with_storage_remotes_returns_true(self) -> None:
        """Active storage_remotes exist → returns True."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1,)
        mock_session.execute.return_value = mock_result

        assert await has_uploader_configured(mock_session) is True


# ---------------------------------------------------------------------------
# Find Deletable (Query Criteria)
# ---------------------------------------------------------------------------


class TestFindDeletable:
    """Tests for find_deletable() query construction."""

    async def test_housekeeping_criteria_with_uploader(self) -> None:
        """Housekeeping + uploader: query includes uploaded=true + analysis check."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(1, "raw.wav", "proc.wav")]
        mock_session.execute.return_value = mock_result

        rows = await find_deletable(
            mock_session, RetentionMode.HOUSEKEEPING, 50, uploader_active=True
        )
        assert len(rows) == 1
        # Verify the SQL contained 'uploaded = true'
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        assert "uploaded = true" in sql_text

    async def test_housekeeping_no_uploader_fallback(self) -> None:
        """Housekeeping + no uploader: query skips uploaded condition."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(1, "raw.wav", "proc.wav")]
        mock_session.execute.return_value = mock_result

        rows = await find_deletable(
            mock_session, RetentionMode.HOUSEKEEPING, 50, uploader_active=False
        )
        assert len(rows) == 1
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        assert "uploaded = true" not in sql_text

    async def test_defensive_criteria_with_uploader(self) -> None:
        """Defensive + uploader: query includes uploaded=true only."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        await find_deletable(mock_session, RetentionMode.DEFENSIVE, 50, uploader_active=True)
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        assert "uploaded = true" in sql_text
        assert "analysis_state" not in sql_text

    async def test_defensive_no_uploader_fallback(self) -> None:
        """Defensive + no uploader: query deletes all non-deleted recordings."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        await find_deletable(mock_session, RetentionMode.DEFENSIVE, 50, uploader_active=False)
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        assert "uploaded = true" not in sql_text

    async def test_panic_criteria(self) -> None:
        """Panic: deletes oldest files regardless of status."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(1, "raw.wav", "proc.wav")]
        mock_session.execute.return_value = mock_result

        rows = await find_deletable(mock_session, RetentionMode.PANIC, 50, uploader_active=True)
        assert len(rows) == 1
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        assert "uploaded" not in sql_text
        assert "analysis_state" not in sql_text

    async def test_idle_returns_empty(self) -> None:
        """Idle mode: returns empty list (no query executed)."""
        mock_session = AsyncMock()
        rows = await find_deletable(mock_session, RetentionMode.IDLE, 50, uploader_active=True)
        assert rows == []
        mock_session.execute.assert_not_called()

    async def test_batch_size_respected(self) -> None:
        """Batch size is passed as LIMIT parameter."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        await find_deletable(mock_session, RetentionMode.PANIC, 25, uploader_active=True)
        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["batch"] == 25


# ---------------------------------------------------------------------------
# File Deletion
# ---------------------------------------------------------------------------


class TestDeleteFiles:
    """Tests for delete_files() physical removal."""

    def test_deletes_existing_files(self, tmp_path: Path) -> None:
        """Both raw and processed WAV files are deleted."""
        raw = tmp_path / "sensor" / "data" / "raw" / "test.wav"
        proc = tmp_path / "sensor" / "data" / "processed" / "test.wav"
        raw.parent.mkdir(parents=True)
        proc.parent.mkdir(parents=True)
        raw.write_bytes(b"\x00" * 100)
        proc.write_bytes(b"\x00" * 100)

        removed = delete_files(
            tmp_path, "sensor/data/raw/test.wav", "sensor/data/processed/test.wav"
        )
        assert removed == 2
        assert not raw.exists()
        assert not proc.exists()

    def test_missing_file_no_error(self, tmp_path: Path) -> None:
        """Non-existing files are gracefully skipped."""
        removed = delete_files(tmp_path, "nonexistent/raw.wav", "nonexistent/proc.wav")
        assert removed == 0


# ---------------------------------------------------------------------------
# Soft Delete (DB)
# ---------------------------------------------------------------------------


class TestSoftDelete:
    """Tests for soft_delete() DB flag update."""

    async def test_soft_delete_updates_db(self) -> None:
        """soft_delete sets local_deleted=true via SQL UPDATE."""
        mock_session = AsyncMock()
        await soft_delete(mock_session, recording_id=42)
        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["id"] == 42


# ---------------------------------------------------------------------------
# Panic Filesystem Fallback
# ---------------------------------------------------------------------------


class TestPanicFilesystemFallback:
    """Tests for panic_filesystem_fallback() mtime-based cleanup."""

    def test_deletes_oldest_first(self, tmp_path: Path) -> None:
        """Oldest files (by mtime) are deleted first."""
        sensor_dir = tmp_path / "sensor" / "data" / "processed"
        sensor_dir.mkdir(parents=True)

        # Create 3 files with different mtimes
        for i, name in enumerate(["old.wav", "mid.wav", "new.wav"]):
            f = sensor_dir / name
            f.write_bytes(b"\x00" * 100)
            os.utime(f, (1000 + i * 100, 1000 + i * 100))

        deleted = panic_filesystem_fallback(tmp_path, batch_size=2)
        assert deleted == 2
        # Only newest should remain
        remaining = list(sensor_dir.glob("*.wav"))
        assert len(remaining) == 1
        assert remaining[0].name == "new.wav"

    def test_batch_size_limits_deletion(self, tmp_path: Path) -> None:
        """Batch size limits the number of files deleted."""
        sensor_dir = tmp_path / "sensor" / "data" / "raw"
        sensor_dir.mkdir(parents=True)

        for i in range(10):
            (sensor_dir / f"file_{i:02d}.wav").write_bytes(b"\x00" * 100)

        deleted = panic_filesystem_fallback(tmp_path, batch_size=3)
        assert deleted == 3
        remaining = list(sensor_dir.glob("*.wav"))
        assert len(remaining) == 7

    def test_empty_workspace_returns_zero(self, tmp_path: Path) -> None:
        """Empty workspace → 0 files deleted, no crash."""
        deleted = panic_filesystem_fallback(tmp_path, batch_size=50)
        assert deleted == 0

    def test_getmtime_oserror_skips_file(self, tmp_path: Path) -> None:
        """OSError during getmtime (race condition) gracefully skips the file."""
        sensor_dir = tmp_path / "sensor" / "data" / "processed"
        sensor_dir.mkdir(parents=True)
        f = sensor_dir / "vanished.wav"
        f.write_bytes(b"\x00" * 100)

        with patch("os.path.getmtime", side_effect=OSError("File vanished")):
            deleted = panic_filesystem_fallback(tmp_path, batch_size=10)

        assert deleted == 0

    def test_unlink_oserror_logged(self, tmp_path: Path) -> None:
        """OSError during unlink is caught and logged, file not counted."""
        sensor_dir = tmp_path / "sensor" / "data" / "processed"
        sensor_dir.mkdir(parents=True)
        f = sensor_dir / "locked.wav"
        f.write_bytes(b"\x00" * 100)

        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            deleted = panic_filesystem_fallback(tmp_path, batch_size=10)

        assert deleted == 0


# ---------------------------------------------------------------------------
# Full Cleanup Cycle
# ---------------------------------------------------------------------------


class TestRunCleanup:
    """Tests for run_cleanup() full cycle."""

    async def test_idle_skips_cleanup(self) -> None:
        """Below warning threshold → returns idle result, no queries."""
        mock_session = AsyncMock()
        settings = ProcessorSettings()

        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=50.0):
            result = await run_cleanup(mock_session, Path("/data"), settings)

        assert result.mode == RetentionMode.IDLE
        assert result.files_deleted == 0

    async def test_db_offline_housekeeping_skips(self) -> None:
        """DB offline during Housekeeping → exception propagated, no data loss."""
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("DB offline")
        settings = ProcessorSettings()

        with (
            patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0),
            pytest.raises(Exception, match="DB offline"),
        ):
            await run_cleanup(mock_session, Path("/data"), settings)

    async def test_metrics_reported(self) -> None:
        """Result contains disk usage, mode, and deletion counts."""
        mock_session = AsyncMock()
        # has_uploader_configured returns False
        mock_result_uploader = MagicMock()
        mock_result_uploader.fetchone.return_value = None
        # find_deletable returns empty
        mock_result_find = MagicMock()
        mock_result_find.fetchall.return_value = []

        mock_session.execute.side_effect = [mock_result_uploader, mock_result_find]
        settings = ProcessorSettings()

        with patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0):
            result = await run_cleanup(mock_session, Path("/data"), settings)

        assert isinstance(result, JanitorResult)
        assert result.mode == RetentionMode.HOUSEKEEPING
        assert result.disk_usage_percent == 75.0
        assert result.files_deleted == 0
        assert result.uploader_fallback is True

    async def test_delete_error_records_in_result(self) -> None:
        """Exception during delete_files/soft_delete is caught, counted, and logged."""
        mock_session = AsyncMock()
        # has_uploader_configured → no uploader
        mock_result_uploader = MagicMock()
        mock_result_uploader.fetchone.return_value = None
        # find_deletable → 1 row
        mock_result_find = MagicMock()
        mock_result_find.fetchall.return_value = [(1, "raw.wav", "proc.wav")]

        mock_session.execute.side_effect = [mock_result_uploader, mock_result_find]
        settings = ProcessorSettings()

        with (
            patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0),
            patch(
                "silvasonic.processor.janitor.delete_files",
                side_effect=OSError("disk error"),
            ),
        ):
            result = await run_cleanup(mock_session, Path("/data"), settings)

        assert result.errors == 1
        assert result.files_deleted == 0
        assert "proc.wav" in result.error_details
        mock_session.commit.assert_not_called()

    async def test_successful_deletion_commits_session(self) -> None:
        """Successful file deletion triggers session.commit()."""
        mock_session = AsyncMock()
        # has_uploader_configured → no uploader
        mock_result_uploader = MagicMock()
        mock_result_uploader.fetchone.return_value = None
        # find_deletable → 1 row
        mock_result_find = MagicMock()
        mock_result_find.fetchall.return_value = [(1, "raw.wav", "proc.wav")]
        # soft_delete UPDATE result (needed for 3rd execute call)
        mock_result_update = MagicMock()

        mock_session.execute.side_effect = [
            mock_result_uploader,
            mock_result_find,
            mock_result_update,
        ]
        settings = ProcessorSettings()

        with (
            patch("silvasonic.processor.janitor.get_disk_usage", return_value=75.0),
            patch("silvasonic.processor.janitor.delete_files", return_value=2),
        ):
            result = await run_cleanup(mock_session, Path("/data"), settings)

        assert result.files_deleted == 1
        assert result.errors == 0
        mock_session.commit.assert_called_once()


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
        mock_result_uploader = MagicMock()
        mock_result_uploader.fetchone.return_value = None
        mock_result_find = MagicMock()
        mock_result_find.fetchall.return_value = []
        mock_session.execute.side_effect = [mock_result_uploader, mock_result_find]

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
