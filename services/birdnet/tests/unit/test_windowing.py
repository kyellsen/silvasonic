"""Unit tests for BirdNET analysis windows and the seasonal species filter."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from silvasonic.birdnet.service import (
    MODEL_SR,
    WINDOW_SAMPLES,
    BirdNETService,
    birdnet_week,
    window_starts,
)

STEP_NO_OVERLAP = WINDOW_SAMPLES


def _seconds(*values: float) -> list[int]:
    return [int(v * MODEL_SR) for v in values]


@pytest.fixture
def service(tmp_path: Path) -> BirdNETService:
    with patch.dict(
        "os.environ",
        {
            "SILVASONIC_INSTANCE_ID": "birdnet-test",
            "SILVASONIC_WORKSPACE_DIR": str(tmp_path),
        },
    ):
        from silvasonic.core.schemas.settings import BirdnetSettings, StationSettings

        svc = BirdNETService()
        svc.birdnet_config = BirdnetSettings()
        svc.station_config = StationSettings(latitude=53.5, longitude=10.0)
        return svc


@pytest.mark.unit
class TestWindowStarts:
    """Every sample of a recording lands in at least one analysis window."""

    def test_ten_second_segment_gets_end_aligned_tail_window(self) -> None:
        """10 s with 3 s windows and no overlap: the last second is analysed too."""
        assert window_starts(10 * MODEL_SR, STEP_NO_OVERLAP) == _seconds(0, 3, 6, 7)

    @pytest.mark.parametrize("duration_s", [3.0, 4.5, 9.0, 10.0, 15.0, 29.9])
    @pytest.mark.parametrize("overlap_s", [0.0, 0.5, 1.5])
    def test_windows_cover_every_sample(self, duration_s: float, overlap_s: float) -> None:
        """The union of all windows is the whole recording."""
        n = int(duration_s * MODEL_SR)
        step = int((3.0 - overlap_s) * MODEL_SR)
        covered = np.zeros(n, dtype=bool)
        for start in window_starts(n, step):
            covered[start : start + WINDOW_SAMPLES] = True
        assert covered.all()

    def test_exact_multiple_adds_no_extra_window(self) -> None:
        """9 s divides into three windows; no tail window is needed."""
        assert window_starts(9 * MODEL_SR, STEP_NO_OVERLAP) == _seconds(0, 3, 6)

    def test_short_recording_gets_one_padded_window(self) -> None:
        """A 2 s recording is analysed as one zero-padded window."""
        assert window_starts(2 * MODEL_SR, STEP_NO_OVERLAP) == [0]

    def test_tiny_recording_is_skipped(self) -> None:
        """Less than 1.5 s of audio is not analysed."""
        assert window_starts(MODEL_SR, STEP_NO_OVERLAP) == []


@pytest.mark.unit
class TestBirdnetWeek:
    """BirdNET's year has 48 weeks, four per month."""

    @pytest.mark.parametrize(
        ("day", "week"),
        [
            (datetime(2026, 1, 1, tzinfo=UTC), 1),
            (datetime(2026, 1, 8, tzinfo=UTC), 2),
            (datetime(2026, 1, 31, tzinfo=UTC), 4),
            (datetime(2026, 2, 1, tzinfo=UTC), 5),
            (datetime(2026, 6, 15, tzinfo=UTC), 23),
            (datetime(2026, 12, 31, tzinfo=UTC), 48),
        ],
    )
    def test_week_mapping(self, day: datetime, week: int) -> None:
        """Days 1-7 are the month's first week, 22 onwards its fourth."""
        assert birdnet_week(day) == week


@pytest.mark.unit
@pytest.mark.asyncio
class TestTailDetection:
    """A call in the last second of a segment is detected."""

    async def test_detection_in_final_second(self, service: BirdNETService) -> None:
        """The model sees the end-aligned window and its hit is stored with the week."""
        audio = np.zeros(10 * MODEL_SR, dtype=np.float32)
        audio[int(9.5 * MODEL_SR)] = 1.0  # the "call" sits in the final second

        interpreter = MagicMock()
        interpreter.get_input_details.return_value = [{"index": 0}]
        interpreter.get_output_details.return_value = [{"index": 1}]
        fed: dict[str, np.ndarray] = {}

        def set_tensor(_idx: int, chunk: np.ndarray) -> None:
            fed["chunk"] = chunk

        def get_tensor(_idx: int) -> np.ndarray:
            hit = fed["chunk"].max() > 0
            return np.array([[10.0 if hit else -10.0]], dtype=np.float32)

        interpreter.set_tensor.side_effect = set_tensor
        interpreter.get_tensor.side_effect = get_tensor

        loop = MagicMock()

        def run_in_executor(_executor: Any, func: Any, *args: Any) -> asyncio.Future[Any]:
            future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
            future.set_result(func(*args))
            return future

        loop.run_in_executor.side_effect = run_in_executor

        recording = MagicMock()
        recording.id = 7
        recording.started_at = datetime(2026, 6, 15, 6, 0, 0, tzinfo=UTC)

        with (
            patch("silvasonic.birdnet.service.sf.read", return_value=(audio, MODEL_SR)),
            patch("silvasonic.birdnet.service.sf.write"),
            patch("silvasonic.birdnet.service.asyncio.get_running_loop", return_value=loop),
        ):
            detections = await service._process_recording(
                recording,
                Path("/tmp/fake.wav"),
                interpreter,
                ["Turdus merula_Eurasian Blackbird"],
                np.array([True]),
                True,
                23,
            )

        assert len(detections) == 1
        det = detections[0]
        assert det.started_at == datetime(2026, 6, 15, 6, 0, 7, tzinfo=UTC)
        assert det.ended_at == datetime(2026, 6, 15, 6, 0, 10, tzinfo=UTC)
        assert det.details["week"] == 23
        assert det.analyzer == "birdnet"
        assert det.label == "Turdus merula_Eurasian Blackbird"
        assert det.species_id == "turdus-merula"
        assert service.birdnet_config is not None
        assert det.details["overlap_s"] == service.birdnet_config.overlap_s
        assert det.details["min_confidence"] == service.birdnet_config.min_confidence


@pytest.mark.unit
@pytest.mark.asyncio
class TestSeasonalMask:
    """The species mask follows the recording's date, not the clock at startup."""

    async def test_mask_built_for_recording_week(self, service: BirdNETService) -> None:
        """A June recording analysed in any month is filtered with June's species."""
        recording = MagicMock()
        recording.started_at = datetime(2026, 6, 15, 6, 0, 0, tzinfo=UTC)
        recording.analysis_state = {}

        class FakeSession:
            async def execute(self, *args: Any, **kwargs: Any) -> Any:
                result = MagicMock()
                result.scalar_one_or_none.return_value = recording
                result.scalar_one.return_value = 1
                result.scalars.return_value = []
                return result

            async def commit(self) -> None:
                pass

            async def rollback(self) -> None:
                pass

        class FakeSessionCtx:
            async def __aenter__(self) -> FakeSession:
                return FakeSession()

            async def __aexit__(self, *exc: object) -> None:
                pass

        async def process(*args: Any, **kwargs: Any) -> list[Any]:
            service._shutdown_event.set()
            return []

        with (
            patch("builtins.open"),
            patch("silvasonic.birdnet.service.Interpreter"),
            patch("silvasonic.birdnet.service.get_session", return_value=FakeSessionCtx()),
            patch.object(service, "_refresh_config"),
            patch.object(service, "_previous_segment_path", return_value=None),
            patch.object(service, "_process_recording", side_effect=process) as mock_process,
            patch.object(
                service, "_get_allowed_species_mask", return_value=(np.array([True]), True)
            ) as mock_mask,
            patch("silvasonic.birdnet.service.Path.exists", return_value=True),
        ):
            await service.run()

        mock_mask.assert_called_once()
        assert mock_mask.call_args.args[1] == 23
        assert mock_process.call_args.args[6] == 23  # week
