"""BirdNET refuses audio that is not at the model's 48 kHz (ADR-0011)."""

import asyncio
import uuid
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
        from silvasonic.core.schemas.settings import BirdnetSettings, StationSettings

        svc = BirdNETService()
        svc.birdnet_config = BirdnetSettings()
        svc.station_config = StationSettings(latitude=53.5, longitude=10.0)
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
        recording.started_at = datetime(2026, 6, 15, 6, 0, 0, tzinfo=UTC)

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
        recording.id = uuid.UUID("0193f1c2-7b3a-7c4e-9d55-0a1b2c3d4e5f")
        recording.started_at = datetime(2026, 6, 15, 6, 0, 0, tzinfo=UTC)
        recording.analysis_state = {}
        recording.processed_path = "mic/data/processed/cd_rate.wav"

        class FakeSession:
            async def execute(self, *args: Any, **kwargs: Any) -> Any:
                result = MagicMock()
                result.scalar_one.return_value = 1
                return result

        async def finish(recording_id: Any, state: Any, detections: Any = None) -> None:
            # Store the entry as the database would
            recording.analysis_state = {"birdnet": state.to_json()}

        class FakeSessionCtx:
            async def __aenter__(self) -> FakeSession:
                return FakeSession()

            async def __aexit__(self, *exc: object) -> None:
                pass

        async def process(*args: Any, **kwargs: Any) -> list[Any]:
            service._shutdown_event.set()
            raise UnsupportedSampleRateError("cd_rate.wav is at 44100 Hz")

        with (
            patch("builtins.open"),
            patch("silvasonic.birdnet.service.Interpreter"),
            patch("silvasonic.birdnet.service.get_session", return_value=FakeSessionCtx()),
            patch.object(service, "_refresh_config"),
            patch.object(service, "_claim_next_recording", AsyncMock(return_value=recording)),
            patch.object(service, "_finish_recording", side_effect=finish),
            patch.object(service, "_previous_segment_path", return_value=None),
            patch.object(service, "_process_recording", side_effect=process),
            patch.object(
                service, "_get_allowed_species_mask", return_value=(np.array([True]), False)
            ),
            patch("silvasonic.birdnet.service.Path.exists", return_value=True),
        ):
            await service.run()

        entry = recording.analysis_state["birdnet"]
        assert entry["state"] == "skipped"
        assert entry["reason"] == "sample_rate_unsupported"
        assert entry["detection_count"] is None
        assert entry["finished_at"].endswith("Z")
        # The error text stays in the log
        assert "44100" not in str(recording.analysis_state)


@pytest.mark.unit
@pytest.mark.asyncio
class TestNativeSampleRate:
    """BirdNET judges the file it reads, not ``recordings.sample_rate_hz``.

    Since ADR-0033 the column holds the microphone's native rate, e.g.
    384 kHz for an ultrasonic microphone whose processed stream is 48 kHz.
    """

    async def test_native_rate_with_48k_processed_file_is_analysed(
        self, service: BirdNETService, tmp_path: Path
    ) -> None:
        """A 384 kHz microphone's 48 kHz processed file is analysed."""
        import soundfile as sf

        processed = tmp_path / "processed.wav"
        sf.write(str(processed), np.zeros(3 * 48_000, dtype=np.float32), 48_000)

        interpreter = MagicMock()
        interpreter.get_input_details.return_value = [{"index": 0}]
        interpreter.get_output_details.return_value = [{"index": 0}]
        interpreter.get_tensor.return_value = np.full((1, 1), -10.0, dtype=np.float32)

        recording = MagicMock()
        recording.sample_rate_hz = 384_000
        recording.started_at = datetime(2026, 6, 15, 6, 0, 0, tzinfo=UTC)

        with patch(
            "silvasonic.birdnet.service.asyncio.get_running_loop",
            return_value=_inline_loop(),
        ):
            detections = await service._process_recording(
                recording,
                processed,
                interpreter,
                ["Turdus merula_Eurasian Blackbird"],
                np.array([True]),
                False,
            )

        assert detections == []
        interpreter.invoke.assert_called()

    async def test_raw_only_file_off_48k_is_refused(
        self, service: BirdNETService, tmp_path: Path
    ) -> None:
        """A raw-only recording whose raw file is 96 kHz is refused, whatever the column says."""
        import soundfile as sf

        raw = tmp_path / "raw.wav"
        sf.write(str(raw), np.zeros(3 * 96_000, dtype=np.float32), 96_000)

        interpreter = MagicMock()
        recording = MagicMock()
        recording.sample_rate_hz = 48_000
        recording.started_at = datetime(2026, 6, 15, 6, 0, 0, tzinfo=UTC)

        with (
            patch(
                "silvasonic.birdnet.service.asyncio.get_running_loop",
                return_value=_inline_loop(),
            ),
            pytest.raises(UnsupportedSampleRateError, match="96000 Hz"),
        ):
            await service._process_recording(
                recording,
                raw,
                interpreter,
                ["Turdus merula_Eurasian Blackbird"],
                np.array([True]),
                False,
            )

        interpreter.invoke.assert_not_called()
