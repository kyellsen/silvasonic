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


def _mock_db_result(rows: list[Any]) -> MagicMock:
    result_mock = MagicMock()
    result_mock.all.return_value = rows
    return result_mock


@pytest.mark.unit
async def test_finds_pending_recordings(mock_session: AsyncMock) -> None:
    """Test standard case of finding un-uploaded recordings."""
    rec = MagicMock()
    rec.id = 1
    rec.file_raw = "/fake/file.wav"
    rec.time = datetime(2024, 1, 1, 12, tzinfo=UTC)

    mock_session.execute.return_value = _mock_db_result([(rec, "mic_1")])

    pending = await find_pending_uploads(mock_session, batch_size=50)

    assert len(pending) == 1
    assert pending[0].recording_id == 1
    assert pending[0].file_raw == Path("/fake/file.wav")
    assert pending[0].sensor_id == "mic_1"
    # station_name should be empty initially
    assert pending[0].station_name == ""


@pytest.mark.unit
async def test_empty_result(mock_session: AsyncMock) -> None:
    """Test behavior when no pending recordings exist."""
    mock_session.execute.return_value = _mock_db_result([])
    pending = await find_pending_uploads(mock_session)
    assert len(pending) == 0


@pytest.mark.unit
async def test_batch_size_respected(mock_session: AsyncMock) -> None:
    """Test the limit clause corresponds to the batch size."""
    mock_session.execute.return_value = _mock_db_result([])
    await find_pending_uploads(mock_session, batch_size=5)

    # Extract the passed SQLAlchemy Select statement constraint
    stmt = mock_session.execute.call_args[0][0]
    assert stmt.compile(compile_kwargs={"literal_binds": True}).string.endswith("LIMIT 5")
