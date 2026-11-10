"""Unit tests for BirdNET analysis windows."""

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
        from silvasonic.core.schemas.system_config import BirdnetSettings, SystemSettings

        svc = BirdNETService()
        svc.birdnet_config = BirdnetSettings()
        svc.system_config = SystemSettings(latitude=53.5, longitude=10.0)
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
@pytest.mark.asyncio
class TestTailDetection:
    """A call in the last second of a segment is detected."""

    async def test_detection_in_final_second(self, service: BirdNETService) -> None:
        """The model sees the end-aligned window; its hit starts 7 s in."""
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

        def run_in_executor(_executor: Any, func: Any, *args: Any) -> "asyncio.Future[Any]":
            future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
            future.set_result(func(*args))
            return future

        loop.run_in_executor.side_effect = run_in_executor

        recording = MagicMock()
        recording.id = 7
        recording.time = datetime(2026, 6, 15, 6, 0, 0, tzinfo=UTC)

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
            )

        assert len(detections) == 1
        det = detections[0]
        assert det.time == datetime(2026, 6, 15, 6, 0, 7, tzinfo=UTC)
        assert det.end_time == datetime(2026, 6, 15, 6, 0, 10, tzinfo=UTC)
