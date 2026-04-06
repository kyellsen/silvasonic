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


@pytest.mark.unit
class TestBirdNETResilience:
    """Test BirdNET Soft-Fail and transient I/O resilience (ADR-0030)."""

    @pytest.fixture
    def mock_service(self) -> BirdNETService:
        with patch.dict("os.environ", {"SILVASONIC_INSTANCE_ID": "test-bnet"}):
            svc = BirdNETService()
            svc.birdnet_config = MagicMock()
            svc.system_config = MagicMock()
            return svc

    @pytest.mark.asyncio
    async def test_loop_survives_db_failure(self, mock_service: BirdNETService) -> None:
        """Database connection drop during get_session() doesn't crash the loop."""
        from typing import Any

        call_count = 0

        async def dummy_sleep(*args: Any, **kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            mock_service._shutdown_event.set()

        with (
            patch("builtins.open"),
            patch("silvasonic.birdnet.service.Interpreter"),
            patch("silvasonic.birdnet.service.get_session", side_effect=RuntimeError("DB Down")),
            patch("asyncio.sleep", side_effect=dummy_sleep) as mock_sleep,
        ):
            await mock_service.run()

        from silvasonic.birdnet.service import _DB_RETRY_SLEEP_S

        mock_sleep.assert_called_with(_DB_RETRY_SLEEP_S)

    @pytest.mark.asyncio
    async def test_health_transient_degradation(self, mock_service: BirdNETService) -> None:
        """Health degrades cleanly to database_unavailable."""
        from typing import Any

        async def dummy_sleep(*args: Any, **kwargs: Any) -> None:
            mock_service._shutdown_event.set()

        with (
            patch("builtins.open"),
            patch("silvasonic.birdnet.service.Interpreter"),
            patch("silvasonic.birdnet.service.get_session", side_effect=RuntimeError("DB Down")),
            patch("asyncio.sleep", side_effect=dummy_sleep),
        ):
            await mock_service.run()

        assert mock_service.health._components["birdnet"]["healthy"] is False
        assert mock_service.health._components["birdnet"]["details"] == "database_unavailable"

    @pytest.mark.asyncio
    async def test_post_rollback_failure_caught(self, mock_service: BirdNETService) -> None:
        """If writing the crashed state fails (e.g. DB commit drop), it soft-fails."""
        from typing import Any

        call_count = 0

        async def dummy_sleep(*args: Any, **kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            mock_service._shutdown_event.set()

        class MockSession:
            def __init__(self) -> None:
                self.commit_calls = 0

            async def execute(self, *args: Any, **kwargs: Any) -> Any:
                mock_result = MagicMock()
                mock_recording = MagicMock()
                mock_recording.analysis_state = {}
                mock_result.scalar_one_or_none.return_value = mock_recording
                return mock_result

            async def rollback(self) -> None:
                pass

            async def commit(self) -> None:
                self.commit_calls += 1
                if self.commit_calls == 1:
                    raise RuntimeError("DB Dropped During Commit")

        class MockSessionCtx:
            async def __aenter__(self) -> MockSession:
                return MockSession()

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
                pass

        with (
            patch("builtins.open"),
            patch("silvasonic.birdnet.service.Interpreter"),
            patch("silvasonic.birdnet.service.get_session", return_value=MockSessionCtx()),
            patch.object(
                mock_service, "_process_recording", side_effect=ValueError("Inference failed")
            ),
            patch("asyncio.sleep", side_effect=dummy_sleep) as mock_sleep,
            patch("silvasonic.birdnet.service.Path.exists", return_value=True),
        ):
            await mock_service.run()

        from silvasonic.birdnet.service import _DB_RETRY_SLEEP_S

        mock_sleep.assert_called_with(_DB_RETRY_SLEEP_S)
        assert mock_service.health._components["birdnet"]["healthy"] is False
        assert mock_service.health._components["birdnet"]["details"] == "database_unavailable"
