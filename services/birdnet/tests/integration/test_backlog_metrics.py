"""Integration tests for BirdNET backlog counting metric."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from silvasonic.birdnet.service import BirdNETService
from silvasonic.core.database.check import check_database_connection
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.models.system import Microphone
from silvasonic.core.database.session import get_session
from testcontainers.postgres import PostgresContainer


@pytest.fixture
async def seeded_backlog_db(postgres_container: PostgresContainer) -> AsyncGenerator[None]:
    """Seed the database with pending and analyzed recordings."""
    await check_database_connection()

    async with get_session() as session:
        # Seed Profile & Device to satisfy FKs
        prof = MicrophoneProfile(slug="test-prof", name="test-prof", config={"gain_adjust": 0})
        session.add(prof)
        dev = Microphone(
            hardware_id="test-mic",
            name="dummy",
            serial_number="1234",
            model="dummy",
            profile_slug="test-prof",
        )
        session.add(dev)
        await session.flush()

        # 1. Pending recording
        r1 = Recording(
            started_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            microphone_id=dev.id,
            raw_path="/tmp/fake1.wav",
            processed_path="/tmp/fake1.wav",
            duration_s=10.0,
            sample_rate_hz=48000,
            raw_size_bytes=100,
            analysis_state={},
        )
        # 2. Another pending recording
        r2 = Recording(
            started_at=datetime(2024, 1, 1, 12, 1, tzinfo=UTC),
            microphone_id=dev.id,
            raw_path="/tmp/fake2.wav",
            processed_path="/tmp/fake2.wav",
            duration_s=10.0,
            sample_rate_hz=48000,
            raw_size_bytes=100,
            analysis_state={},
        )
        # 3. Analyzed recording
        r3 = Recording(
            started_at=datetime(2024, 1, 1, 12, 2, tzinfo=UTC),
            microphone_id=dev.id,
            raw_path="/tmp/fake3.wav",
            processed_path="/tmp/fake3.wav",
            duration_s=10.0,
            sample_rate_hz=48000,
            raw_size_bytes=100,
            analysis_state={
                "birdnet": {
                    "state": "done",
                    "reason": None,
                    "finished_at": "2024-01-01T12:10:00Z",
                    "detection_count": 0,
                }
            },
        )
        # 4. Deleted recording (should not be counted)
        r4 = Recording(
            started_at=datetime(2024, 1, 1, 12, 3, tzinfo=UTC),
            microphone_id=dev.id,
            raw_path="/tmp/fake4.wav",
            processed_path="/tmp/fake4.wav",
            duration_s=10.0,
            sample_rate_hz=48000,
            raw_size_bytes=100,
            analysis_state={},
            deleted_at=datetime(2024, 1, 2, tzinfo=UTC),
            deletion_reason="retention",
        )

        session.add_all([r1, r2, r3, r4])
        await session.commit()

    yield


@pytest.mark.integration
@pytest.mark.asyncio
class TestBacklogMetrics:
    """Verify backlog query counts exactly the required rows against real DB."""

    async def test_backlog_count_pending_recordings(
        self,
        postgres_container: PostgresContainer,
        seeded_backlog_db: None,
        tmp_path: Path,
    ) -> None:
        """Worker fetch loop accurately counts pending unanalyzed recordings."""
        with patch.dict(
            "os.environ",
            {
                "SILVASONIC_INSTANCE_ID": "w-test",
                "SILVASONIC_WORKSPACE_DIR": str(tmp_path),
            },
        ):
            svc = BirdNETService()

        # Let the service loop run once but skip inference
        with patch.object(svc, "_shutdown_event"):
            cast(MagicMock, svc._shutdown_event.is_set).side_effect = [False, True]

            with (
                patch("silvasonic.birdnet.service.Interpreter"),
                patch.object(svc, "_get_allowed_species_mask", return_value=(None, False)),
                patch.object(svc, "load_config"),
                patch.object(svc, "_refresh_config"),
                patch("builtins.open"),
                patch.object(svc, "birdnet_config"),
                patch.object(svc, "station_config"),
            ):
                # Ensure the loop exits immediately and doesn't do processing
                assert svc.birdnet_config is not None
                svc.birdnet_config.processing_order = "oldest_first"
                svc.birdnet_config.thread_count = 1
                await svc.run()

        # After one iteration of the run() loop, _backlog_pending should be populated
        # There are 4 recordings: 2 pending, 1 done, 1 deleted. Backlog should be 2.
        assert svc._backlog_pending == 2

    async def test_backlog_zero_when_all_analyzed(
        self,
        postgres_container: PostgresContainer,
        tmp_path: Path,
    ) -> None:
        """When all recordings are analyzed or deleted, backlog is zero."""
        await check_database_connection()

        async with get_session() as session:
            prof = MicrophoneProfile(
                slug="test-prof2", name="test-prof2", config={"gain_adjust": 0}
            )
            session.add(prof)
            dev = Microphone(
                hardware_id="test-mic2",
                name="dummy",
                serial_number="4321",
                model="dummy",
                profile_slug="test-prof2",
            )
            session.add(dev)
            await session.flush()

            r1 = Recording(
                started_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
                microphone_id=dev.id,
                raw_path="/tmp/f.wav",
                processed_path="/tmp/f.wav",
                duration_s=10.0,
                sample_rate_hz=48000,
                raw_size_bytes=100,
                analysis_state={
                    "birdnet": {
                        "state": "done",
                        "reason": None,
                        "finished_at": "2024-01-01T12:10:00Z",
                        "detection_count": 0,
                    }
                },
            )
            r2 = Recording(
                started_at=datetime(2024, 1, 1, 12, 1, tzinfo=UTC),
                microphone_id=dev.id,
                raw_path="/tmp/f.wav",
                processed_path="/tmp/f.wav",
                duration_s=10.0,
                sample_rate_hz=48000,
                raw_size_bytes=100,
                analysis_state={},
                deleted_at=datetime(2024, 1, 2, tzinfo=UTC),
                deletion_reason="retention",
            )
            session.add_all([r1, r2])
            await session.commit()

        with patch.dict(
            "os.environ",
            {
                "SILVASONIC_INSTANCE_ID": "w-test",
                "SILVASONIC_WORKSPACE_DIR": str(tmp_path),
            },
        ):
            svc = BirdNETService()

        # Let the service loop run once but skip inference
        with patch.object(svc, "_shutdown_event"):
            cast(MagicMock, svc._shutdown_event.is_set).side_effect = [False, True]

            with (
                patch("silvasonic.birdnet.service.Interpreter"),
                patch.object(svc, "_get_allowed_species_mask", return_value=(None, False)),
                patch.object(svc, "load_config"),
                patch.object(svc, "_refresh_config"),
                patch("builtins.open"),
                patch.object(svc, "birdnet_config"),
                patch.object(svc, "station_config"),
            ):
                assert svc.birdnet_config is not None
                svc.birdnet_config.processing_order = "oldest_first"
                svc.birdnet_config.thread_count = 1
                await svc.run()

        # Only 'done' or 'deleted' recordings, backlog is 0
        assert svc._backlog_pending == 0
