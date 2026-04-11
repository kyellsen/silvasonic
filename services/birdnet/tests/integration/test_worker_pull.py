"""Integration tests for BirdNET Worker Pull."""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from silvasonic.birdnet.service import BirdNETService
from silvasonic.core.database.check import check_database_connection
from silvasonic.core.database.models.detections import Detection
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.models.system import Device, SystemConfig
from silvasonic.core.database.session import get_session
from sqlalchemy import select
from testcontainers.postgres import PostgresContainer


@pytest.fixture
async def seeded_db(postgres_container: PostgresContainer) -> AsyncGenerator[None]:
    """Seed the database with a device, profile, and system config."""
    # Ensure DB is reachable
    await check_database_connection()

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
    with patch.dict(
        "os.environ", {"SILVASONIC_INSTANCE_ID": "w1", "SILVASONIC_WORKSPACE_DIR": "/tmp"}
    ):
        w1 = BirdNETService()
    with patch.dict(
        "os.environ", {"SILVASONIC_INSTANCE_ID": "w2", "SILVASONIC_WORKSPACE_DIR": "/tmp"}
    ):
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_resolves_relative_db_paths(
    postgres_container: PostgresContainer,
    tmp_path: Path,
) -> None:
    """BirdNET must prefix relative DB paths with recordings_dir to find audio files.

    Regression test for: 'File missing for processing' errors caused by BirdNET
    resolving relative paths (stored by the indexer) against the container CWD
    instead of the configured RECORDINGS_DIR mount point.
    """
    import numpy as np
    import soundfile as sf  # type: ignore[import-untyped]

    # Create a real WAV in the correct directory structure
    workspace = "test-mic-001"
    stream = "data/processed"
    filename = "2024-01-01T12-00-00Z_10s_aabbccdd_00000000.wav"
    relative_path = f"{workspace}/{stream}/{filename}"

    wav_dir = tmp_path / workspace / stream
    wav_dir.mkdir(parents=True)
    wav_path = wav_dir / filename

    sr = 48000
    duration_s = 3.0
    n_samples = int(sr * duration_s)
    samples = np.zeros(n_samples, dtype=np.float32)
    sf.write(str(wav_path), samples, sr, subtype="FLOAT")

    # Seed DB with relative path (as real indexer stores it)
    async with get_session() as session:
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
        prof = MicrophoneProfile(slug="test-prof", name="test-prof", config={"gain_adjust": 0})
        session.add(prof)
        dev = Device(name="test-mic", serial_number="1234", model="dummy", profile_slug="test-prof")
        session.add(dev)
        await session.flush()

        from datetime import UTC, datetime

        rec = Recording(
            time=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            sensor_id="test-mic",
            file_raw=relative_path,
            file_processed=relative_path,
            duration=duration_s,
            sample_rate=sr,
            filesize_raw=wav_path.stat().st_size,
            analysis_state={},
        )
        session.add(rec)
        await session.commit()

    # Create service with RECORDINGS_DIR pointing at tmp_path
    with patch.dict(
        "os.environ",
        {
            "SILVASONIC_INSTANCE_ID": "test-rel",
            "SILVASONIC_RECORDINGS_DIR": str(tmp_path),
            "SILVASONIC_WORKSPACE_DIR": str(tmp_path),
        },
    ):
        svc = BirdNETService()

    await svc.load_config()

    # Run one iteration with real path resolution but mocked inference
    async def mock_process(
        self: Any, recording: Recording, *args: list[Any], **kwargs: dict[str, Any]
    ) -> list[Detection]:
        return []

    with (
        patch.object(BirdNETService, "_process_recording", new=mock_process),
        patch("silvasonic.birdnet.service.Interpreter"),
        patch.object(BirdNETService, "_get_allowed_species_mask", return_value=(None, False)),
        patch("builtins.open"),
    ):
        task = asyncio.create_task(svc.run())
        await asyncio.sleep(0.5)
        svc._shutdown_event.set()
        await task

    # Verify: recording was processed, NOT marked as failed_file_missing
    async with get_session() as session:
        rec = (
            await session.execute(
                select(Recording).where(Recording.file_processed == relative_path)
            )
        ).scalar_one()
        state = rec.analysis_state.get("birdnet", "")
        assert state != "failed_file_missing", (
            f"BirdNET failed to find file with relative path. "
            f"Expected 'done', got analysis_state={rec.analysis_state}"
        )
        assert state == "done", (
            f"Recording should be marked as done, got analysis_state={rec.analysis_state}"
        )
