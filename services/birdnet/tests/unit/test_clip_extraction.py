import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from silvasonic.birdnet.service import MODEL_SR, BirdNETService


@pytest.fixture
def service(tmp_path: Path) -> BirdNETService:
    with patch.dict(
        "os.environ",
        {
            "SILVASONIC_INSTANCE_ID": "birdnet-test",
            "SILVASONIC_WORKSPACE_DIR": str(tmp_path),
        },
    ):
        from silvasonic.birdnet.settings import BirdnetEnvSettings
        from silvasonic.core.schemas.system_config import BirdnetSettings, SystemSettings

        env_settings = BirdnetEnvSettings()
        svc = BirdNETService()
        svc.env_settings = env_settings

        svc.clips_dir = tmp_path / "clips"
        svc.clips_dir.mkdir(exist_ok=True)

        svc.birdnet_config = BirdnetSettings(clip_padding_seconds=1.0)
        svc.system_config = SystemSettings()

        return svc


@pytest.mark.unit
@pytest.mark.asyncio
class TestClipExtraction:
    """Test BirdNET extraction of 3-second padded WAV files."""

    async def test_clip_extraction_writes_wav(self, service: BirdNETService) -> None:
        """The loop should write bounded audio clips using Soundfile."""
        # Setup dummy audio (10 seconds)
        audio_length = 10 * MODEL_SR
        dummy_audio = np.ones(audio_length, dtype=np.float32)

        # Mock dependencies in run_in_executor
        mock_loop = MagicMock()

        def run_in_executor_mock(executor: Any, func: Any, *args: Any) -> asyncio.Task[Any]:
            return asyncio.create_task(self._sync_to_async(func, *args))

        mock_loop.run_in_executor.side_effect = run_in_executor_mock

        # Patch everything inside so we can call exactly the bounds logic
        # Actually it's easier to assert that slice is properly requested
        # without running the full massive run_loop.

        mock_interpreter = MagicMock()
        mock_interpreter.get_input_details.return_value = [{"index": 0}]
        mock_interpreter.get_output_details.return_value = [{"index": 0}]

        # Simulate an immediate positive hit for the first 3s
        def mock_infer() -> None:
            # Return high score array so index 0 is > threshold
            res = np.full((1, 2), -10.0, dtype=np.float32)
            res[0, 0] = 5.0
            mock_interpreter.get_tensor.return_value = res

        mock_interpreter.invoke.side_effect = mock_infer

        # To speed up test, stop processing immediately after first window iteration
        service._shutdown_event = MagicMock()
        service._shutdown_event.is_set.side_effect = [False, True]

        # Mock the recording object
        recording = MagicMock()
        recording.id = 42
        # Mock time
        from datetime import UTC, datetime

        recording.time = datetime(2024, 1, 1, tzinfo=UTC)

        labels = ["Turdus_merula"]
        allowed_mask = np.array([True, True])

        with (
            patch("silvasonic.birdnet.service.sf.write") as mock_sf_write,
            patch("silvasonic.birdnet.service.asyncio.get_running_loop", return_value=mock_loop),
            patch("silvasonic.birdnet.service.sf.read", return_value=(dummy_audio, MODEL_SR)),
        ):
            detections = await service._process_recording(
                recording,
                Path("/tmp/fake.wav"),
                mock_interpreter,
                labels,
                allowed_mask,
                loc_filter_active=False,
            )

        assert len(detections) == 1

        # 1. Assert Database payload path
        # 42_0_3000_Turdusmerula.wav
        assert detections[0].clip_path == "clips/42_0_3000_Turdusmerula.wav"

        # 2. Assert padding slice
        # First chunk starts at 0. Window is 3.0s (144000 samples). Padding is 1.0s (48000 samples)
        # Bounded between 0 and 10s. So start=0, end=144000+48000 = 192000
        mock_sf_write.assert_called_once()
        args, _ = mock_sf_write.call_args
        assert args[0] == str(service.clips_dir / "42_0_3000_Turdusmerula.wav")
        assert len(args[1]) == int(4.0 * MODEL_SR)

    async def _sync_to_async(self, func: Any, *args: Any) -> Any:
        return func(*args)

    async def test_clip_extraction_soft_fails(self, service: BirdNETService) -> None:
        """If Soundfile fails, the detection should still persist but without clip_path."""
        dummy_audio = np.ones(10 * MODEL_SR, dtype=np.float32)
        mock_loop = MagicMock()

        def run_in_executor_mock(executor: Any, func: Any, *args: Any) -> asyncio.Task[Any]:
            return asyncio.create_task(self._sync_to_async(func, *args))

        mock_loop.run_in_executor.side_effect = run_in_executor_mock

        mock_interpreter = MagicMock()
        mock_interpreter.get_input_details.return_value = [{"index": 0}]
        mock_interpreter.get_output_details.return_value = [{"index": 0}]

        def mock_infer() -> None:
            res = np.full((1, 2), -10.0, dtype=np.float32)
            res[0, 0] = 5.0
            mock_interpreter.get_tensor.return_value = res

        mock_interpreter.invoke.side_effect = mock_infer
        service._shutdown_event = MagicMock()
        service._shutdown_event.is_set.side_effect = [False, True]

        recording = MagicMock()
        recording.id = 42
        from datetime import UTC, datetime

        recording.time = datetime(2024, 1, 1, tzinfo=UTC)

        labels = ["Corvus_corax"]
        allowed_mask = np.array([True, True])

        with (
            patch("silvasonic.birdnet.service.sf.write", side_effect=OSError("Disk Full")),
            patch("silvasonic.birdnet.service.asyncio.get_running_loop", return_value=mock_loop),
            patch("silvasonic.birdnet.service.sf.read", return_value=(dummy_audio, MODEL_SR)),
        ):
            detections = await service._process_recording(
                recording,
                Path("/tmp/fake.wav"),
                mock_interpreter,
                labels,
                allowed_mask,
                loc_filter_active=False,
            )

        # Detection should not crash, it should just lack clip path
        assert len(detections) == 1
        assert detections[0].clip_path is None
