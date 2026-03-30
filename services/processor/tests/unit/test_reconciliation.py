"""Unit tests for the Reconciliation Audit module.

Tests the startup audit that heals Split-Brain state by marking
orphaned recordings as ``local_deleted = true``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from silvasonic.processor import reconciliation


@pytest.mark.unit
class TestReconciliationAudit:
    """Verify Reconciliation Audit logic."""

    async def test_missing_file_marked_deleted(self, tmp_path: Path) -> None:
        """DB row with local_deleted=false, file absent → sets local_deleted=true."""
        # Mock: SELECT returns one row with a non-existent file
        select_result = MagicMock()
        select_result.fetchall.return_value = [
            (42, "mic-01/data/processed/missing.wav"),
        ]

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[select_result, AsyncMock()])
        session.commit = AsyncMock()

        count = await reconciliation.run_audit(session, tmp_path)
        assert count == 1
        session.commit.assert_called_once()

    async def test_existing_file_unchanged(self, tmp_path: Path) -> None:
        """DB row with local_deleted=false, file present → no change."""
        # Create the file on disk
        wav = tmp_path / "mic-01" / "data" / "processed" / "exists.wav"
        wav.parent.mkdir(parents=True)
        wav.write_bytes(b"RIFF" + b"\x00" * 100)

        select_result = MagicMock()
        select_result.fetchall.return_value = [
            (1, "mic-01/data/processed/exists.wav"),
        ]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=select_result)
        session.commit = AsyncMock()

        count = await reconciliation.run_audit(session, tmp_path)
        assert count == 0
        # No commit needed — nothing changed
        session.commit.assert_not_called()

    async def test_already_deleted_row_skipped(self, tmp_path: Path) -> None:
        """Rows with local_deleted=true are not returned by the query at all."""
        # Empty result: the SQL WHERE clause filters them out
        select_result = MagicMock()
        select_result.fetchall.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(return_value=select_result)
        session.commit = AsyncMock()

        count = await reconciliation.run_audit(session, tmp_path)
        assert count == 0

    async def test_reconciled_count_reported(self, tmp_path: Path) -> None:
        """Returns correct count of reconciled (missing) rows."""
        select_result = MagicMock()
        select_result.fetchall.return_value = [
            (1, "mic-01/data/processed/gone1.wav"),
            (2, "mic-01/data/processed/gone2.wav"),
            (3, "mic-01/data/processed/gone3.wav"),
        ]

        # Each UPDATE call returns a new mock
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[select_result, AsyncMock(), AsyncMock(), AsyncMock()]
        )
        session.commit = AsyncMock()

        count = await reconciliation.run_audit(session, tmp_path)
        assert count == 3

    async def test_raw_only_recording_file_checked(self, tmp_path: Path) -> None:
        """Raw-only recording (file_processed=NULL) uses file_raw for check.

        Regression test for Bug #2: When file_processed is NULL,
        COALESCE(file_processed, file_raw) returns file_raw. The audit
        must not crash with TypeError (PosixPath / NoneType).

        See: Processor Logs 2026-03-30 — reconciliation_failed TypeError.
        """
        # Create the raw file on disk
        raw_wav = tmp_path / "rode-nt-usb-p3d6" / "data" / "raw" / "audio.wav"
        raw_wav.parent.mkdir(parents=True)
        raw_wav.write_bytes(b"RIFF" + b"\x00" * 100)

        # COALESCE returns file_raw since file_processed is NULL
        select_result = MagicMock()
        select_result.fetchall.return_value = [
            (10, "rode-nt-usb-p3d6/data/raw/audio.wav"),
        ]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=select_result)
        session.commit = AsyncMock()

        count = await reconciliation.run_audit(session, tmp_path)
        assert count == 0  # File exists, no reconciliation needed
        session.commit.assert_not_called()

    async def test_null_check_file_skipped(self, tmp_path: Path) -> None:
        """Row where both file_processed and file_raw are NULL is skipped.

        Edge case safety: should never happen in practice but the audit
        must not crash.
        """
        select_result = MagicMock()
        select_result.fetchall.return_value = [
            (99, None),  # COALESCE(NULL, NULL) = NULL
        ]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=select_result)
        session.commit = AsyncMock()

        count = await reconciliation.run_audit(session, tmp_path)
        assert count == 0
        session.commit.assert_not_called()
