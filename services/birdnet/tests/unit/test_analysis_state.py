"""The worker writes structured ``analysis_state`` entries (ADR-0033)."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from silvasonic.birdnet.service import BirdNETService


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
        svc.station_config = StationSettings()
        return svc


def _recording() -> MagicMock:
    recording = MagicMock()
    recording.id = uuid.UUID("0193f1c2-7b3a-7c4e-9d55-0a1b2c3d4e5f")
    recording.started_at = datetime(2026, 6, 15, 6, 0, 0, tzinfo=UTC)
    recording.processed_path = "mic/data/processed/seg.wav"
    recording.raw_path = "mic/data/raw/seg.wav"
    recording.analysis_state = {}
    return recording


async def _run_once(
    service: BirdNETService,
    recording: MagicMock,
    process: Any,
    *,
    file_exists: bool = True,
) -> MagicMock:
    """Run one worker iteration on ``recording``; return a mock of the stored detections.

    The worker claims through ``_claim_next_recording`` and writes its result
    through ``_finish_recording`` (ADR-0037). The fake finish stores the
    entry on ``recording`` as the database would.
    """
    add_all = MagicMock()

    async def finish(recording_id: Any, state: Any, detections: Any = None) -> None:
        assert recording_id == recording.id
        if detections:
            add_all(detections)
        recording.analysis_state = {**recording.analysis_state, "birdnet": state.to_json()}
        service._shutdown_event.set()

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

    with (
        patch("builtins.open"),
        patch("silvasonic.birdnet.service.Interpreter"),
        patch("silvasonic.birdnet.service.get_session", return_value=FakeSessionCtx()),
        patch("silvasonic.birdnet.service.register_species", new=AsyncMock()) as ensure,
        patch.object(service, "_refresh_config"),
        patch.object(service, "_claim_next_recording", AsyncMock(return_value=recording)),
        patch.object(service, "_finish_recording", side_effect=finish),
        patch.object(service, "_previous_segment_path", return_value=None),
        patch.object(service, "_process_recording", side_effect=process),
        patch.object(service, "_get_allowed_species_mask", return_value=(np.array([True]), False)),
        patch("silvasonic.birdnet.service.Path.exists", return_value=file_exists),
    ):
        await service.run()
    add_all.ensure = ensure
    return add_all


def _assert_entry(entry: dict[str, Any], state: str, reason: str | None, count: int | None) -> None:
    assert set(entry) == {"state", "reason", "finished_at", "detection_count"}
    assert entry["state"] == state
    assert entry["reason"] == reason
    assert entry["detection_count"] == count
    # RFC 3339 UTC
    assert entry["finished_at"].endswith("Z")
    datetime.fromisoformat(entry["finished_at"].replace("Z", "+00:00"))


@pytest.mark.unit
@pytest.mark.asyncio
class TestAnalysisState:
    """done, failed and skipped carry a reason code and a count, never error text."""

    async def test_done_counts_detections_and_registers_species(
        self, service: BirdNETService
    ) -> None:
        recording = _recording()
        det_a = MagicMock(label="Turdus merula_Eurasian Blackbird")
        det_b = MagicMock(label="Erithacus rubecula_European Robin")

        async def process(*args: Any, **kwargs: Any) -> list[Any]:
            return [det_a, det_b]

        add_all = await _run_once(service, recording, process)

        _assert_entry(recording.analysis_state["birdnet"], "done", None, 2)
        add_all.assert_called_once_with([det_a, det_b])
        add_all.ensure.assert_awaited_once()
        assert add_all.ensure.await_args.args[0] == {
            "Turdus merula_Eurasian Blackbird",
            "Erithacus rubecula_European Robin",
        }

    async def test_done_without_detections(self, service: BirdNETService) -> None:
        recording = _recording()

        async def process(*args: Any, **kwargs: Any) -> list[Any]:
            return []

        add_all = await _run_once(service, recording, process)

        _assert_entry(recording.analysis_state["birdnet"], "done", None, 0)
        add_all.ensure.assert_not_awaited()

    async def test_failure_stores_code_not_text(self, service: BirdNETService) -> None:
        recording = _recording()

        async def process(*args: Any, **kwargs: Any) -> list[Any]:
            raise ValueError("tensor shape mismatch in layer 7")

        await _run_once(service, recording, process)

        _assert_entry(recording.analysis_state["birdnet"], "failed", "error", None)
        assert "tensor" not in str(recording.analysis_state)

    async def test_missing_file(self, service: BirdNETService) -> None:
        recording = _recording()
        process = AsyncMock(return_value=[])

        await _run_once(service, recording, process, file_exists=False)

        _assert_entry(recording.analysis_state["birdnet"], "failed", "file_missing", None)
        process.assert_not_awaited()
