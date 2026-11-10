"""BirdNET refuses audio that is not at the model's 48 kHz (ADR-0011)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from silvasonic.birdnet.service import BirdNETService, UnsupportedSampleRateError


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


def _inline_loop() -> MagicMock:
    """An event loop stand-in whose executor runs the function at once."""
    loop = MagicMock()

    def run_in_executor(_executor: Any, func: Any, *args: Any) -> "asyncio.Future[Any]":
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        future.set_result(func(*args))
        return future

    loop.run_in_executor.side_effect = run_in_executor
    return loop


@pytest.mark.unit
@pytest.mark.asyncio
class TestUnsupportedSampleRate:
    """A recording off 48 kHz is skipped, not analysed with scaled-wrong windows."""

    async def test_off_rate_audio_raises(self, service: BirdNETService) -> None:
        """44.1 kHz audio raises before any inference runs."""
        interpreter = MagicMock()
        recording = MagicMock()
        recording.time = datetime(2026, 6, 15, 6, 0, 0, tzinfo=UTC)

        with (
            patch(
                "silvasonic.birdnet.service.sf.read",
                return_value=(np.zeros(441_000, dtype=np.float32), 44_100),
            ),
            patch(
                "silvasonic.birdnet.service.asyncio.get_running_loop",
                return_value=_inline_loop(),
            ),
            pytest.raises(UnsupportedSampleRateError, match="44100 Hz"),
        ):
            await service._process_recording(
                recording,
                Path("/tmp/cd_rate.wav"),
                interpreter,
                ["Turdus merula_Eurasian Blackbird"],
                np.array([True]),
                False,
            )

        interpreter.invoke.assert_not_called()

    async def test_run_marks_recording_skipped(self, service: BirdNETService) -> None:
        """The worker records why, so the recording is not picked up again."""
        recording = MagicMock()
        recording.id = 3
        recording.time = datetime(2026, 6, 15, 6, 0, 0, tzinfo=UTC)
        recording.file_processed = "mic/data/processed/cd_rate.wav"

        class FakeSession:
            async def execute(self, *args: Any, **kwargs: Any) -> Any:
                result = MagicMock()
                result.scalar_one.return_value = 1
                return result

        class FakeSessionCtx:
            async def __aenter__(self) -> FakeSession:
                return FakeSession()

            async def __aexit__(self, *exc: object) -> None:
                pass

        async def process(*args: Any, **kwargs: Any) -> list[Any]:
            service._shutdown_event.set()
            raise UnsupportedSampleRateError("cd_rate.wav is at 44100 Hz")

        finish = AsyncMock()
        with (
            patch("builtins.open"),
            patch("silvasonic.birdnet.service.Interpreter"),
            patch("silvasonic.birdnet.service.get_session", return_value=FakeSessionCtx()),
            patch.object(service, "_refresh_config"),
            patch.object(service, "_claim_next_recording", AsyncMock(return_value=recording)),
            patch.object(service, "_finish_recording", finish),
            patch.object(service, "_previous_segment_path", return_value=None),
            patch.object(service, "_process_recording", side_effect=process),
            patch.object(
                service, "_get_allowed_species_mask", return_value=(np.array([True]), False)
            ),
            patch("silvasonic.birdnet.service.Path.exists", return_value=True),
        ):
            await service.run()

        finish.assert_awaited_once_with(3, "skipped_sample_rate")
