"""Unit tests for the work poller."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from silvasonic.processor.modules.work_poller import find_pending_uploads


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def recordings_dir(tmp_path: Path) -> Path:
    """Provide a realistic recordings_dir base path."""
    return tmp_path / "recorder"


def _mock_db_result(rows: list[Any]) -> MagicMock:
    result_mock = MagicMock()
    result_mock.all.return_value = rows
    return result_mock


@pytest.mark.unit
async def test_finds_pending_recordings(mock_session: AsyncMock, recordings_dir: Path) -> None:
    """Test standard case of finding un-uploaded recordings."""
    rec = MagicMock()
    rec.id = 1
    rec.file_raw = "ultramic/data/raw/file.wav"
    rec.time = datetime(2024, 1, 1, 12, tzinfo=UTC)

    mock_session.execute.return_value = _mock_db_result([(rec, "mic_1", "test_profile")])

    pending = await find_pending_uploads(mock_session, recordings_dir, batch_size=50)

    assert len(pending) == 1
    assert pending[0].recording_id == 1
    assert pending[0].file_raw == recordings_dir / "ultramic/data/raw/file.wav"
    assert pending[0].sensor_id == "mic_1"
    # station_name should be empty initially
    assert pending[0].station_name == ""


@pytest.mark.unit
async def test_empty_result(mock_session: AsyncMock, recordings_dir: Path) -> None:
    """Test behavior when no pending recordings exist."""
    mock_session.execute.return_value = _mock_db_result([])
    pending = await find_pending_uploads(mock_session, recordings_dir)
    assert len(pending) == 0


@pytest.mark.unit
async def test_batch_size_respected(mock_session: AsyncMock, recordings_dir: Path) -> None:
    """Test the limit clause corresponds to the batch size."""
    mock_session.execute.return_value = _mock_db_result([])
    await find_pending_uploads(mock_session, recordings_dir, batch_size=5)

    # Extract the passed SQLAlchemy Select statement constraint
    stmt = mock_session.execute.call_args[0][0]
    assert stmt.compile(compile_kwargs={"literal_binds": True}).string.endswith("LIMIT 5")


# ────────────────────────────────────────────────────
# Regression tests for file_missing bug
# ────────────────────────────────────────────────────


@pytest.mark.unit
async def test_pending_upload_file_raw_is_absolute(
    mock_session: AsyncMock, recordings_dir: Path
) -> None:
    """find_pending_uploads prepends recordings_dir to file_raw.

    Regression: Without the base directory, file_raw is a relative
    path that resolves against CWD, causing upload_worker.file_missing
    for every recording.
    """
    rec = MagicMock()
    rec.id = 42
    rec.file_raw = "rode-nt-usb-p3d6/data/raw/2026-04-03T18-05-21Z_15s_dc67adae_00000000.wav"
    rec.time = datetime(2026, 4, 3, 18, 5, 21, tzinfo=UTC)

    mock_session.execute.return_value = _mock_db_result([(rec, "19f7-0003-port3-6", "rode_nt_usb")])

    pending = await find_pending_uploads(mock_session, recordings_dir, batch_size=10)

    assert len(pending) == 1
    assert pending[0].file_raw.is_absolute(), (
        f"file_raw must be absolute but got: {pending[0].file_raw}"
    )
    expected = recordings_dir / rec.file_raw
    assert pending[0].file_raw == expected


@pytest.mark.unit
async def test_pending_upload_preserves_relative_structure(
    mock_session: AsyncMock, recordings_dir: Path
) -> None:
    """Verify the full relative path structure is preserved under recordings_dir.

    The DB stores paths like `sensor/data/raw/filename.wav`; the resolved
    absolute path must be `recordings_dir / sensor/data/raw/filename.wav`.
    """
    rec = MagicMock()
    rec.id = 7
    rec.file_raw = (
        "ultramic-384-evo-034f/data/processed/2026-04-03T18-05-20Z_15s_8a4b57f5_00000000.wav"
    )
    rec.time = datetime(2026, 4, 3, 18, 5, 20, tzinfo=UTC)

    mock_session.execute.return_value = _mock_db_result(
        [(rec, "0869-0389-00000000034F", "ultramic_384_evo")]
    )

    pending = await find_pending_uploads(mock_session, recordings_dir, batch_size=10)

    assert pending[0].file_raw.parts[-4:] == (
        "ultramic-384-evo-034f",
        "data",
        "processed",
        "2026-04-03T18-05-20Z_15s_8a4b57f5_00000000.wav",
    )


# ────────────────────────────────────────────────────
# Regression tests: Retry limit
# ────────────────────────────────────────────────────


@pytest.mark.unit
async def test_find_pending_uploads_accepts_max_retries(
    mock_session: AsyncMock, recordings_dir: Path
) -> None:
    """find_pending_uploads accepts a max_retries parameter.

    Regression: Without retry limits, failed uploads are re-polled
    endlessly every 30s, creating an ever-growing retry storm that
    blocks the upload queue.
    """
    mock_session.execute.return_value = _mock_db_result([])

    # Must accept max_retries without error
    pending = await find_pending_uploads(mock_session, recordings_dir, batch_size=50, max_retries=3)
    assert pending == []
