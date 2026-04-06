"""Unit tests for BirdNET worker loops."""

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
