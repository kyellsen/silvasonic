"""BirdNET analyses calls that a segment boundary cuts in two."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
from silvasonic.birdnet.service import (
    MODEL_SR,
    SEAM_SAMPLES,
    BirdNETService,
    is_contiguous,
    read_tail,
)
from silvasonic.core.database.models.recordings import Recording

T0 = datetime(2026, 6, 15, 6, 0, 0, tzinfo=UTC)
MIC_ID = uuid.UUID("0193f1c2-7b3a-7c4e-9d55-0a1b2c3d4e5f")


@pytest.fixture
def service(tmp_path: Path) -> BirdNETService:
    with patch.dict(
        "os.environ",
        {
            "SILVASONIC_INSTANCE_ID": "birdnet-test",
            "SILVASONIC_WORKSPACE_DIR": str(tmp_path),
            "SILVASONIC_RECORDINGS_DIR": str(tmp_path / "recorder"),
        },
    ):
        from silvasonic.core.schemas.settings import BirdnetSettings, StationSettings

        svc = BirdNETService()
        svc.birdnet_config = BirdnetSettings()
        svc.station_config = StationSettings(latitude=53.5, longitude=10.0)
        return svc


def _inline_loop() -> MagicMock:
    """An event loop stand-in whose executor runs the function at once."""
    loop = MagicMock()

    def run_in_executor(_executor: Any, func: Any, *args: Any) -> asyncio.Future[Any]:
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        future.set_result(func(*args))
        return future

    loop.run_in_executor.side_effect = run_in_executor
    return loop


def _fake_interpreter() -> MagicMock:
    """A model that scores a hit for every window holding non-silent audio."""
    interpreter = MagicMock()
    interpreter.get_input_details.return_value = [{"index": 0}]
    interpreter.get_output_details.return_value = [{"index": 1}]
    fed: dict[str, np.ndarray] = {}

    def set_tensor(_idx: int, chunk: np.ndarray) -> None:
        fed["chunk"] = chunk

    def get_tensor(_idx: int) -> np.ndarray:
        hit = np.abs(fed["chunk"]).max() > 0
        return np.array([[10.0 if hit else -10.0]], dtype=np.float32)

    interpreter.set_tensor.side_effect = set_tensor
    interpreter.get_tensor.side_effect = get_tensor
    return interpreter


@pytest.mark.unit
class TestIsContiguous:
    """Consecutive segments of one run follow each other within a second."""

    @pytest.mark.parametrize(
        ("start", "expected"),
        [
            (T0 + timedelta(seconds=10), True),
            (T0 + timedelta(seconds=11), True),  # rounded segment names
            (T0 + timedelta(seconds=9), True),
            (T0 + timedelta(seconds=12), False),  # a gap: FFmpeg restarted
            (T0 + timedelta(seconds=60), False),
        ],
    )
    def test_contiguity(self, start: datetime, expected: bool) -> None:
        """Only a segment starting where the previous one ended counts."""
        assert is_contiguous(T0, 10.0, start) is expected


@pytest.mark.unit
class TestReadTail:
    """The lead-in is the previous segment's last 1.5 s."""

    def test_returns_last_samples(self, tmp_path: Path) -> None:
        """The tail is read without loading the whole file."""
        path = tmp_path / "prev.wav"
        audio = np.linspace(-0.5, 0.5, 10 * MODEL_SR, dtype=np.float32)
        sf.write(str(path), audio, MODEL_SR, subtype="FLOAT")

        tail = read_tail(path, SEAM_SAMPLES)

        assert tail is not None
        np.testing.assert_array_equal(tail, audio[-SEAM_SAMPLES:])

    def test_other_rate_gives_none(self, tmp_path: Path) -> None:
        """A lead-in at another rate is not spliced onto 48 kHz audio."""
        path = tmp_path / "prev.wav"
        sf.write(str(path), np.zeros(441_000, dtype=np.float32), 44_100)

        assert read_tail(path, SEAM_SAMPLES) is None

    def test_too_short_gives_none(self, tmp_path: Path) -> None:
        """A previous segment shorter than the lead-in is not used."""
        path = tmp_path / "prev.wav"
        sf.write(str(path), np.zeros(MODEL_SR, dtype=np.float32), MODEL_SR)

        assert read_tail(path, SEAM_SAMPLES) is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestSeamWindow:
    """A call at the very end of one segment is found from the next."""

    async def test_call_at_boundary_is_detected(
        self, service: BirdNETService, tmp_path: Path
    ) -> None:
        """The seam window spans [-1.5 s, +1.5 s] around the recording's start."""
        prev_audio = np.zeros(10 * MODEL_SR, dtype=np.float32)
        prev_audio[int(9.8 * MODEL_SR)] = 0.5  # the call's first half, before the cut
        prev_path = tmp_path / "prev.wav"
        sf.write(str(prev_path), prev_audio, MODEL_SR, subtype="FLOAT")

        current_path = tmp_path / "current.wav"
        sf.write(str(current_path), np.zeros(10 * MODEL_SR, dtype=np.float32), MODEL_SR)
        recording = MagicMock()
        recording.id = 8
        recording.started_at = T0

        with (
            patch("silvasonic.birdnet.service.sf.write"),
            patch(
                "silvasonic.birdnet.service.asyncio.get_running_loop",
                return_value=_inline_loop(),
            ),
        ):
            detections = await service._process_recording(
                recording,
                current_path,
                _fake_interpreter(),
                ["Turdus merula_Eurasian Blackbird"],
                np.array([True]),
                False,
                lead_in_path=prev_path,
            )

        assert [(d.started_at, d.ended_at) for d in detections] == [
            (T0 - timedelta(seconds=1.5), T0 + timedelta(seconds=1.5))
        ]
        assert detections[0].clip_path == "clips/8_-1500_1500_TurdusmerulaEurasianBlackbird.wav"

    async def test_unreadable_lead_in_is_skipped(self, service: BirdNETService) -> None:
        """A lead-in the Janitor already removed costs only the seam window."""
        current = np.zeros(10 * MODEL_SR, dtype=np.float32)
        current[int(0.5 * MODEL_SR)] = 0.5
        recording = MagicMock()
        recording.id = 9
        recording.started_at = T0

        with (
            patch("silvasonic.birdnet.service.sf.read", return_value=(current, MODEL_SR)),
            patch("silvasonic.birdnet.service.sf.write"),
            patch(
                "silvasonic.birdnet.service.asyncio.get_running_loop",
                return_value=_inline_loop(),
            ),
        ):
            detections = await service._process_recording(
                recording,
                Path("/tmp/current.wav"),
                _fake_interpreter(),
                ["Turdus merula_Eurasian Blackbird"],
                np.array([True]),
                False,
                lead_in_path=Path("/tmp/gone.wav"),
            )

        assert [d.started_at for d in detections] == [T0]


@pytest.mark.unit
@pytest.mark.asyncio
class TestPreviousSegmentPath:
    """The lead-in comes from the same device's directly preceding segment."""

    @staticmethod
    def _session(row: SimpleNamespace | None) -> MagicMock:
        session = MagicMock()
        result = MagicMock()
        result.first.return_value = row

        async def execute(*args: Any, **kwargs: Any) -> MagicMock:
            return result

        session.execute = execute
        return session

    async def test_contiguous_segment_on_disk(self, service: BirdNETService) -> None:
        """A contiguous predecessor whose file exists is used."""
        rel = "mic-01/data/processed/prev.wav"
        (service.recordings_dir / rel).parent.mkdir(parents=True)
        (service.recordings_dir / rel).write_bytes(b"")
        row = SimpleNamespace(
            started_at=T0, duration_s=10.0, processed_path=rel, raw_path="raw.wav"
        )
        recording = Recording(microphone_id=MIC_ID, started_at=T0 + timedelta(seconds=10))

        path = await service._previous_segment_path(self._session(row), recording)

        assert path == service.recordings_dir / rel

    async def test_gap_gives_none(self, service: BirdNETService) -> None:
        """After a gap the two segments do not share a call."""
        row = SimpleNamespace(
            started_at=T0, duration_s=10.0, processed_path=None, raw_path="raw.wav"
        )
        recording = Recording(microphone_id=MIC_ID, started_at=T0 + timedelta(seconds=30))

        path = await service._previous_segment_path(self._session(row), recording)

        assert path is None

    async def test_deleted_file_gives_none(self, service: BirdNETService) -> None:
        """A predecessor the Janitor removed is not used."""
        row = SimpleNamespace(
            started_at=T0, duration_s=10.0, processed_path=None, raw_path="gone.wav"
        )
        recording = Recording(microphone_id=MIC_ID, started_at=T0 + timedelta(seconds=10))

        path = await service._previous_segment_path(self._session(row), recording)

        assert path is None

    async def test_first_segment_gives_none(self, service: BirdNETService) -> None:
        """The first segment of a device has no predecessor."""
        recording = Recording(microphone_id=MIC_ID, started_at=T0)

        path = await service._previous_segment_path(self._session(None), recording)

        assert path is None
