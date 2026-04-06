"""Integration tests for BirdNET Worker Pull."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import patch

import pytest
from silvasonic.birdnet.service import BirdNETService
from silvasonic.core.database.check import check_database_connection
from silvasonic.core.database.models.detections import Detection
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.models.system import Device, SystemConfig
from silvasonic.core.database.session import _get_engine, get_session
from sqlalchemy import select
from testcontainers.postgres import PostgresContainer


@pytest.fixture
async def seeded_db(postgres_container: PostgresContainer) -> AsyncGenerator[None]:
    """Seed the database with a device, profile, and system config."""
    # Ensure DB is reachable
    await check_database_connection()

    engine = _get_engine()
    async with engine.begin() as conn:
        from silvasonic.core.database.models.base import Base

        await conn.run_sync(Base.metadata.create_all)

    async with get_session() as session:
        # 1. System Config
        session.add(SystemConfig(key="system", value={"latitude": 53.55, "longitude": 9.99}))
        session.add(
            SystemConfig(
                key="birdnet",
                value={
                    "confidence_threshold": 0.3,
                    "sensitivity": 1.0,
                    "overlap": 0.0,
                    "threads": 1,
                    "processing_order": "oldest_first",
                },
            )
        )

        # 2. Profile & Device
        prof = MicrophoneProfile(slug="test-prof", name="test-prof", config={"gain_adjust": 0})
        session.add(prof)
        dev = Device(name="test-mic", serial_number="1234", model="dummy", profile_slug="test-prof")
        session.add(dev)
        await session.flush()

        # 3. Two pending recordings
        from datetime import UTC, datetime

        r1 = Recording(
            time=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            sensor_id="test-mic",
            file_raw="/tmp/fake1.wav",
            file_processed="/tmp/fake1.wav",  # Make it exist
            duration=10.0,
            sample_rate=48000,
            filesize_raw=100,
            analysis_state={},
        )
        r2 = Recording(
            time=datetime(2024, 1, 1, 12, 1, tzinfo=UTC),
            sensor_id="test-mic",
            file_raw="/tmp/fake2.wav",
            file_processed="/tmp/fake2.wav",
            duration=10.0,
            sample_rate=48000,
            filesize_raw=100,
            analysis_state={},
        )
        session.add(r1)
        session.add(r2)
        await session.commit()

    yield


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_pull_concurrency(
    postgres_container: PostgresContainer, seeded_db: None
) -> None:
    """Test that multiple workers can pull recordings simultaneously without lock collisions."""
    # Create two service instances with mocked Redis config
    with patch.dict("os.environ", {"SILVASONIC_INSTANCE_ID": "w1"}):
        w1 = BirdNETService()
    with patch.dict("os.environ", {"SILVASONIC_INSTANCE_ID": "w2"}):
        w2 = BirdNETService()

    await w1.load_config()
    await w2.load_config()

    # Mock OS Path existence check so they process the fake recordings
    with patch("silvasonic.birdnet.service.Path.exists", return_value=True):
        # Mock the entire _process_recording function strictly to return 1 dummy Detection
        async def mock_process(
            self: Any, recording: Recording, *args: list[Any], **kwargs: dict[str, Any]
        ) -> list[Detection]:
            from silvasonic.core.schemas.detections import BirdnetDetectionDetails

            # Simulate processing time
            await asyncio.sleep(0.1)
            details = BirdnetDetectionDetails(
                model_version="v2.4",
                sensitivity=1.0,
                overlap=0.0,
                confidence_threshold=0.3,
                location_filter_active=False,
            )
            from datetime import timedelta

            return [
                Detection(
                    recording_id=recording.id,
                    worker="birdnet",
                    time=recording.time,
                    end_time=recording.time + timedelta(seconds=3),
                    label="Turdus",
                    common_name="merula",
                    confidence=0.99,
                    details=details.model_dump(),
                )
            ]

        with (
            patch.object(BirdNETService, "_process_recording", new=mock_process),
            patch("silvasonic.birdnet.service.Interpreter"),
            patch.object(BirdNETService, "_get_allowed_species_mask", return_value=(None, False)),
            patch("builtins.open"),
        ):
            task1 = asyncio.create_task(w1.run())
            task2 = asyncio.create_task(w2.run())

            # Wait long enough for both to do 1 iteration of the sleep(0.1) mock
            await asyncio.sleep(0.5)

            w1._shutdown_event.set()
            w2._shutdown_event.set()
            await asyncio.gather(task1, task2)

    # Verification: Both recordings must be done, exactly 2 detections inserted
    async with get_session() as session:
        recs = (await session.execute(select(Recording))).scalars().all()
        assert len(recs) == 2
        for r in recs:
            assert r.analysis_state.get("birdnet") == "done", "Recording not marked done"

        dets = (await session.execute(select(Detection))).scalars().all()
        assert len(dets) == 2, "Each recording should have exactly 1 detection"
