"""Integration tests for BirdNET clip extraction pipeline."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import sqlalchemy as sa
from silvasonic.birdnet.service import MODEL_SR, BirdNETService
from silvasonic.core.database.check import check_database_connection
from silvasonic.core.database.models.detections import Detection
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.models.system import Device
from silvasonic.core.database.session import get_session
from testcontainers.postgres import PostgresContainer


@pytest.fixture
async def seeded_clip_db(
    postgres_container: PostgresContainer, tmp_path: Path
) -> AsyncGenerator[Path]:
    """Seed the database with a pending recording and return the workspace path."""
    await check_database_connection()

    # Create dummy wav file
    dummy_wav = tmp_path / "dummy.wav"
    dummy_wav.write_bytes(
        b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58"
        b"\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    )

    async with get_session() as session:
        prof = MicrophoneProfile(slug="test-prof-clip", name="test-prof", config={"gain_adjust": 0})
        session.add(prof)
        dev = Device(
            name="test-mic-clip", serial_number="9999", model="dummy", profile_slug="test-prof-clip"
        )
        session.add(dev)
        await session.flush()

        # Pending recording pointing to dummy file
        r1 = Recording(
            time=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            sensor_id="test-mic-clip",
            file_raw="dummy.wav",
            file_processed="dummy.wav",
            duration=10.0,
            sample_rate=48000,
            filesize_raw=100,
            analysis_state={},
        )
        session.add(r1)
        await session.commit()

    yield tmp_path


@pytest.mark.integration
@pytest.mark.asyncio
class TestClipPipeline:
    """Verify that end-to-end BirdNET inference extracts audio clips and sets database path."""

    async def test_successful_clip_extraction(
        self, postgres_container: PostgresContainer, seeded_clip_db: Path
    ) -> None:
        """Integration test for full clip generation pipeline to DB update."""
        with patch.dict(
            "os.environ",
            {
                "SILVASONIC_INSTANCE_ID": "w-test-clip",
                "SILVASONIC_WORKSPACE_DIR": str(seeded_clip_db),
                "SILVASONIC_RECORDINGS_DIR": str(seeded_clip_db),
            },
        ):
            svc = BirdNETService()

        # Mock the event loop executor to run inline
        mock_loop = MagicMock()

        async def _sync_to_async(func: Any, *args: Any) -> Any:
            return func(*args)

        def run_in_executor_mock(executor: Any, func: Any, *args: Any) -> Any:
            import asyncio

            return asyncio.create_task(_sync_to_async(func, *args))

        mock_loop.run_in_executor.side_effect = run_in_executor_mock

        # Setup mocked Interpreter bounds and return score
        mock_interpreter = MagicMock()
        mock_interpreter.get_input_details.return_value = [{"index": 0}]
        mock_interpreter.get_output_details.return_value = [{"index": 0}]

        def mock_infer() -> None:
            res = np.full((1, 2), -10.0, dtype=np.float32)
            res[0, 1] = 5.0  # Hit on Erithacus_rubecula
            mock_interpreter.get_tensor.return_value = res

        mock_interpreter.invoke.side_effect = mock_infer

        svc._shutdown_event = MagicMock()
        svc._shutdown_event.is_set.side_effect = [False] * 10 + [True]

        with (
            patch("silvasonic.birdnet.service.Interpreter", return_value=mock_interpreter),
            patch("silvasonic.birdnet.service.asyncio.get_running_loop", return_value=mock_loop),
            patch.object(
                svc, "_get_allowed_species_mask", return_value=(np.array([True, True]), False)
            ),
            patch("builtins.open"),
            patch.object(svc, "load_config"),
            patch.object(svc, "_refresh_config"),
            patch.object(svc, "birdnet_config"),
            patch.object(svc, "system_config"),
            patch(
                "silvasonic.birdnet.service.sf.read",
                return_value=(np.ones(5 * MODEL_SR, dtype=np.float32), MODEL_SR),
            ),
            patch("silvasonic.birdnet.service.sf.write") as mock_sf_write,
        ):
            assert svc.birdnet_config is not None
            assert svc.system_config is not None
            svc.birdnet_config.processing_order = "oldest_first"
            svc.birdnet_config.threads = 1
            svc.birdnet_config.overlap = 0.0
            svc.birdnet_config.sensitivity = 1.0
            svc.birdnet_config.confidence_threshold = 0.1
            svc.birdnet_config.clip_padding_seconds = 3.0

            svc.system_config.latitude = 0.0
            svc.system_config.longitude = 0.0

            from unittest.mock import mock_open

            mock_file = mock_open(read_data="Dummy_label\nErithacus_rubecula")
            with patch("builtins.open", mock_file):
                await svc.run()

        # Assert SF write was called at least once
        mock_sf_write.assert_called()

        # Query Database
        async with get_session() as session:
            stmt = sa.select(Detection).where(Detection.worker == "birdnet")
            result = await session.execute(stmt)
            detections = result.scalars().all()

        assert len(detections) > 0
        det = detections[0]

        # Check that it properly stripped common name and persisted path
        assert det.label == "Erithacus_rubecula"
        assert det.common_name == "rubecula"
        assert det.clip_path is not None
        assert det.clip_path.startswith("clips/")
        assert det.clip_path.endswith("Erithacusrubecula.wav")
