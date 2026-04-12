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

    async def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        """Path traversal clip_path is silently skipped, DB NOT nullified.

        Security contract: A malicious clip_path like '../../etc/passwd'
        must never resolve outside workspace_root. The guard MUST skip
        the entry entirely — no unlink, no DB nullification.
        """
        from silvasonic.processor.janitor import delete_worker_clips

        session = AsyncMock()
        mock_result = MagicMock()
        # Simulate a detection row with a path-traversal clip_path
        mock_result.fetchall.return_value = [
            ("birdnet", "../../etc/passwd"),
        ]
        session.execute.return_value = mock_result

        removed = await delete_worker_clips(session, 99, tmp_path)

        # Path traversal entry must be skipped entirely
        assert removed == 0
        # Only the SELECT query — NO UPDATE query must happen
        assert session.execute.call_count == 1

    async def test_oserror_causes_partial_nullify_and_raise(self, tmp_path: Path) -> None:
        """OSError during unlink → partial DB nullification + re-raise.

        Data-integrity contract: If clip A deletes successfully but clip B
        hits an OSError, the DB must still be updated for clip A (partial
        nullification), and the OSError must be re-raised so the caller
        can count it as an error.
        """
        from silvasonic.processor.janitor import delete_worker_clips

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("birdnet", "clips/ok.wav"),
            ("birdnet", "clips/broken.wav"),
        ]
        session.execute.return_value = mock_result

        # Create first file (will succeed)
        ok_file = tmp_path / "birdnet" / "clips" / "ok.wav"
        ok_file.parent.mkdir(parents=True)
        ok_file.write_bytes(b"\x00")

        # Create second file but make it fail on unlink
        broken_file = tmp_path / "birdnet" / "clips" / "broken.wav"
        broken_file.write_bytes(b"\x00")

        original_unlink = Path.unlink

        def selective_unlink(
            self_path: Path,
            missing_ok: bool = False,
        ) -> None:
            if self_path.name == "broken.wav":
                raise OSError("Permission denied")
            original_unlink(self_path, missing_ok=missing_ok)

        with (
            patch.object(Path, "unlink", selective_unlink),
            pytest.raises(OSError, match="Permission denied"),
        ):
            await delete_worker_clips(session, 42, tmp_path)

        # Partial nullification: DB update was called for ok.wav only
        assert session.execute.call_count == 2
        update_call = session.execute.call_args_list[1]
        assert update_call[0][1] == {"id": 42, "clip_paths": ["clips/ok.wav"]}


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
        assert result.recordings_deleted == 0

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
        assert result.recordings_deleted == 0

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
        assert result.recordings_deleted == 1
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
        assert result.recordings_deleted == 0

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
        assert result.recordings_deleted == 0


# ---------------------------------------------------------------------------
# run_cleanup — Deletion loop error handling
# ---------------------------------------------------------------------------


class TestRunCleanupErrorHandling:
    """Tests for the three except-paths in run_cleanup's inner for-loop.

    Domain invariants:
    - SQLAlchemyError → rollback + re-raise (split-brain protection)
    - Generic Exception → error counted, continue to next recording
    - Worker-clip failure → error counted, recording deletion NOT aborted
    """

    def _mock_session(
        self,
        rows: list[tuple[int, str, str | None]],
    ) -> AsyncMock:
        """Create a mocked AsyncSession that returns given rows."""
        session = AsyncMock()

        # is_cloud_sync_enabled query → returns False
        cloud_sync_result = MagicMock()
        cloud_sync_result.fetchone.return_value = None
        # find_deletable query → returns rows
        find_result = MagicMock()
        find_result.fetchall.return_value = rows

        session.execute.side_effect = [cloud_sync_result, find_result]
        return session

    async def test_sqlalchemy_error_triggers_rollback_and_reraise(
        self,
    ) -> None:
        """SQLAlchemyError during soft_delete → rollback + raise.

        Split-brain protection: A DB error MUST abort the entire cycle
        immediately and roll back the transaction to prevent inconsistency
        between filesystem state and database state.
        """
        from silvasonic.processor.janitor import run_cleanup
        from sqlalchemy.exc import SQLAlchemyError

        session = self._mock_session([(1, "raw/a.wav", "proc/a.wav")])

        with (
            patch(
                "silvasonic.processor.janitor.delete_files",
                new_callable=AsyncMock,
            ),
            patch(
                "silvasonic.processor.janitor.soft_delete",
                new_callable=AsyncMock,
                side_effect=SQLAlchemyError("DB gone"),
            ),
            pytest.raises(SQLAlchemyError),
        ):
            await run_cleanup(
                session,
                Path("/data/recorder"),
                ProcessorSettings(),
                mode=RetentionMode.HOUSEKEEPING,
                disk_pct=75.0,
            )

        # Rollback MUST have been called
        session.rollback.assert_awaited_once()
        # Commit must NOT have been called (cycle aborted)
        session.commit.assert_not_awaited()

    async def test_generic_exception_counts_error_and_continues(
        self,
    ) -> None:
        """Generic Exception during delete_files → count error, continue.

        Fault-tolerance: A single recording failure (e.g., stale NFS
        handle) must not prevent the remaining batch from being cleaned.
        """
        from silvasonic.processor.janitor import run_cleanup

        session = self._mock_session(
            [
                (1, "raw/a.wav", "proc/a.wav"),
                (2, "raw/b.wav", "proc/b.wav"),
            ]
        )
        # Re-mock execute to handle all subsequent calls too
        cloud_sync_result = MagicMock()
        cloud_sync_result.fetchone.return_value = None
        find_result = MagicMock()
        find_result.fetchall.return_value = [
            (1, "raw/a.wav", "proc/a.wav"),
            (2, "raw/b.wav", "proc/b.wav"),
        ]
        # After find_deletable, soft_delete also calls execute
        session.execute = AsyncMock(side_effect=[cloud_sync_result, find_result])

        call_count = 0

        async def failing_then_ok(*args: object, **kw: object) -> int:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("NFS stale handle")
            return 1

        with (
            patch(
                "silvasonic.processor.janitor.delete_files",
                new_callable=AsyncMock,
                side_effect=failing_then_ok,
            ),
            patch(
                "silvasonic.processor.janitor.soft_delete",
                new_callable=AsyncMock,
            ),
            patch(
                "silvasonic.processor.janitor.delete_worker_clips",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            result = await run_cleanup(
                session,
                Path("/data/recorder"),
                ProcessorSettings(),
                mode=RetentionMode.HOUSEKEEPING,
                disk_pct=75.0,
            )

        # First recording failed, second succeeded
        assert result.recordings_deleted == 1
        assert result.errors == 1
        assert "proc/a.wav" in result.error_details
        # Commit is called (partial progress saved)
        session.commit.assert_awaited_once()

    async def test_worker_clip_failure_does_not_abort_recording_deletion(
        self,
    ) -> None:
        """Worker-clip error is counted but recording stays deleted.

        Domain invariant: 'A broken worker clip must NEVER prevent
        recording deletion'. The soft_delete already happened, so the
        error is just logged and counted.
        """
        from silvasonic.processor.janitor import run_cleanup

        session = self._mock_session([(1, "raw/a.wav", "proc/a.wav")])

        with (
            patch(
                "silvasonic.processor.janitor.delete_files",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(
                "silvasonic.processor.janitor.soft_delete",
                new_callable=AsyncMock,
            ),
            patch(
                "silvasonic.processor.janitor.delete_worker_clips",
                new_callable=AsyncMock,
                side_effect=OSError("clip locked"),
            ),
        ):
            result = await run_cleanup(
                session,
                Path("/data/recorder"),
                ProcessorSettings(),
                mode=RetentionMode.HOUSEKEEPING,
                disk_pct=75.0,
            )

        # Recording WAS deleted despite clip error
        assert result.recordings_deleted == 1
        # But clip error was counted
        assert result.errors == 1
        assert "proc/a.wav" in result.error_details
        # Commit is called — partial NULLs from clip deletion are preserved
        session.commit.assert_awaited_once()
