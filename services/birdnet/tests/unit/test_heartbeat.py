"""Unit tests for BirdNET heartbeat and get_extra_meta implementation."""

from pathlib import Path
from unittest.mock import patch

import pytest
from silvasonic.birdnet.service import BirdNETService


@pytest.fixture
def mock_service(tmp_path: Path) -> BirdNETService:
    with patch.dict(
        "os.environ",
        {
            "SILVASONIC_INSTANCE_ID": "test-bnet",
            "SILVASONIC_WORKSPACE_DIR": str(tmp_path),
        },
    ):
        svc = BirdNETService()
        return svc


@pytest.mark.unit
class TestBirdNETHeartbeatUnit:
    """Verify heartbeat metadata namespace and metrics integration."""

    def test_get_extra_meta_returns_analysis_namespace(self, mock_service: BirdNETService) -> None:
        """get_extra_meta() must return a dict with an 'analysis' key."""
        meta = mock_service.get_extra_meta()
        assert "analysis" in meta
        assert isinstance(meta["analysis"], dict)

    def test_get_extra_meta_backlog_counter(self, mock_service: BirdNETService) -> None:
        """The private _backlog_pending counter must be correctly exposed."""
        mock_service._backlog_pending = 42
        meta = mock_service.get_extra_meta()
        assert meta["analysis"]["backlog_pending"] == 42

    def test_get_extra_meta_stats_integration(self, mock_service: BirdNETService) -> None:
        """Operational statistics are correctly fetched from BirdnetStats and calculated."""
        # Manually force some stats
        mock_service.stats.total_analyzed = 10
        mock_service.stats.total_hits = 15
        mock_service.stats.total_errors = 2
        mock_service.stats.total_duration_s = 5.0  # 5000 ms total for 10 items -> 500ms avg

        meta = mock_service.get_extra_meta()

        assert meta["analysis"]["total_analyzed"] == 10
        assert meta["analysis"]["total_detections"] == 15
        assert meta["analysis"]["total_errors"] == 2
        assert meta["analysis"]["avg_inference_ms"] == 500.0

    def test_get_extra_meta_zero_division_safe(self, mock_service: BirdNETService) -> None:
        """Ensure avg_inference_ms does not cause ZeroDivisionError when no recordings analyzed."""
        mock_service.stats.total_analyzed = 0
        mock_service.stats.total_duration_s = 0.0

        meta = mock_service.get_extra_meta()

        assert meta["analysis"]["avg_inference_ms"] == 0.0
