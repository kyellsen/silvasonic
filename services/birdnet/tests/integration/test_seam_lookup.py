"""The seam window's lead-in lookup against a real database."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from silvasonic.birdnet.service import BirdNETService
from silvasonic.core.database.check import check_database_connection
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.models.system import Device
from silvasonic.core.database.session import get_session

T0 = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def _recording(sensor: str, start: datetime, rel: str) -> Recording:
    return Recording(
        time=start,
        sensor_id=sensor,
        file_raw=rel,
        file_processed=rel,
        duration=10.0,
        sample_rate=48000,
        filesize_raw=100,
        analysis_state={},
    )


@pytest.mark.integration
async def test_previous_segment_lookup(station_db: Path, tmp_path: Path) -> None:
    """Same device, contiguous, on disk: anything else gives no lead-in."""
    await check_database_connection()
    for rel in ("mic-a/first.wav", "mic-a/second.wav", "mic-b/other.wav"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"")

    async with get_session() as session:
        session.add(MicrophoneProfile(slug="prof", name="prof", config={}))
        session.add(Device(name="mic-a", serial_number="a", model="m", profile_slug="prof"))
        session.add(Device(name="mic-b", serial_number="b", model="m", profile_slug="prof"))
        await session.flush()
        first = _recording("mic-a", T0, "mic-a/first.wav")
        second = _recording("mic-a", T0 + timedelta(seconds=10), "mic-a/second.wav")
        after_gap = _recording("mic-a", T0 + timedelta(seconds=40), "mic-a/late.wav")
        # Another device's segment, closer in time than mic-a's predecessor
        other = _recording("mic-b", T0 + timedelta(seconds=5), "mic-b/other.wav")
        session.add_all([first, second, after_gap, other])
        await session.commit()

    with patch.dict(
        "os.environ",
        {
            "SILVASONIC_INSTANCE_ID": "seam-test",
            "SILVASONIC_RECORDINGS_DIR": str(tmp_path),
            "SILVASONIC_WORKSPACE_DIR": str(tmp_path),
        },
    ):
        svc = BirdNETService()

    async with get_session() as session:
        assert await svc._previous_segment_path(session, second) == tmp_path / "mic-a/first.wav"
        assert await svc._previous_segment_path(session, after_gap) is None
        assert await svc._previous_segment_path(session, first) is None
