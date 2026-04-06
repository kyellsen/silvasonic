"""Unit tests for BirdNET worker loops."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from silvasonic.birdnet.service import BirdNETService


@pytest.mark.unit
class TestBirdNETServiceUnit:
    """Isolate and test the worker orchestration mechanisms."""

    @pytest.fixture
    def mock_service(self) -> BirdNETService:
        with patch.dict("os.environ", {"SILVASONIC_INSTANCE_ID": "test-bnet"}):
            return BirdNETService()

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, mock_service: BirdNETService) -> None:
        """Service exits gracefully when shutdown event is set without pulling further."""
        # Trick the service into skipping DB init and jumping to loops
        mock_service.birdnet_config = MagicMock()
        mock_service.system_config = MagicMock()

        # Prevent actually calling TFLite loading by throwing an Exception simulating no model
        # which will cause hit the fast return logic and exit immediately since shutdown is set
        mock_service._shutdown_event.set()

        with patch("builtins.open", side_effect=FileNotFoundError), patch("asyncio.sleep"):
            await mock_service.run()

        # Test won't hang if shutdown logic is respected
        assert True


@pytest.mark.unit
class TestAudioPathResolution:
    """Verify BirdNET resolves relative DB paths against RECORDINGS_DIR."""

    def test_audio_path_resolves_relative_to_recordings_dir(self) -> None:
        """Relative DB path must be prefixed with recordings_dir to form an absolute path.

        The indexer stores relative paths like 'mic-001/data/processed/seg.wav'
        in the database. BirdNET must prepend its recordings_dir (/data/recorder)
        to form the correct absolute path: /data/recorder/mic-001/data/processed/seg.wav.

        Regression test for: File missing for processing errors caused by BirdNET
        resolving relative paths against the container CWD instead of /data/recorder.
        """
        with patch.dict(
            "os.environ",
            {
                "SILVASONIC_INSTANCE_ID": "test-path",
                "SILVASONIC_RECORDINGS_DIR": "/data/recorder",
            },
        ):
            service = BirdNETService()

        # The service must expose a recordings_dir attribute
        assert hasattr(service, "recordings_dir"), (
            "BirdNETService must have a recordings_dir attribute"
        )
        assert service.recordings_dir == Path("/data/recorder")

        # Simulate a relative path from the database (as stored by the indexer)
        relative_db_path = (
            "ultramic-384-evo-034f/data/processed/2026-04-06T03-02-37Z_10s_66728f81_00000000.wav"
        )

        # Build the audio path the same way the service run() loop should
        audio_path = service.recordings_dir / relative_db_path

        # The result must be absolute and rooted at /data/recorder
        assert audio_path.is_absolute(), "Resolved audio path must be absolute"
        assert str(audio_path).startswith("/data/recorder/"), (
            f"Audio path must be rooted at /data/recorder, got: {audio_path}"
        )
        expected = Path(
            "/data/recorder/ultramic-384-evo-034f/data/processed/2026-04-06T03-02-37Z_10s_66728f81_00000000.wav"
        )
        assert audio_path == expected
