from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.controller.container_spec import Tier2ServiceSpec
from silvasonic.controller.worker_evaluator import SystemWorkerEvaluator


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock()


@pytest.mark.asyncio
@pytest.mark.unit
class TestSystemWorkerEvaluator:
    @patch("silvasonic.controller.worker_evaluator.SYSTEM_WORKERS")
    @patch("silvasonic.controller.worker_evaluator.build_worker_spec")
    async def test_evaluate_enabled_workers_only(
        self, mock_build: MagicMock, mock_system_workers: MagicMock, mock_session: AsyncMock
    ) -> None:
        evaluator = SystemWorkerEvaluator()

        # Setup fake SYSTEM_WORKERS
        w1 = MagicMock()
        w1.name = "worker_active"
        w2 = MagicMock()
        w2.name = "worker_inactive"
        mock_system_workers.__iter__.return_value = [w1, w2]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ["worker_active"]
        mock_session.execute.return_value = mock_result

        # Setup fake spec builder
        fake_spec = MagicMock(spec=Tier2ServiceSpec)
        mock_build.return_value = fake_spec

        # Execute
        specs = await evaluator.evaluate(mock_session)

        # Assertions
        assert len(specs) == 1
        assert specs[0] == fake_spec

        # Ensure build_worker_spec was only called for the enabled worker
        mock_build.assert_called_once_with(w1)

    @patch("silvasonic.controller.worker_evaluator.SYSTEM_WORKERS")
    @patch("silvasonic.controller.worker_evaluator.build_worker_spec")
    async def test_evaluate_catches_build_spec_exceptions(
        self, mock_build: MagicMock, mock_system_workers: MagicMock, mock_session: AsyncMock
    ) -> None:
        evaluator = SystemWorkerEvaluator()

        w1 = MagicMock()
        w1.name = "worker_active_error"
        w2 = MagicMock()
        w2.name = "worker_active_ok"
        mock_system_workers.__iter__.return_value = [w1, w2]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            "worker_active_error",
            "worker_active_ok",
        ]
        mock_session.execute.return_value = mock_result

        # Force an exception for the first worker, succeed for the second
        fake_spec = MagicMock(spec=Tier2ServiceSpec)
        mock_build.side_effect = [Exception("build failed"), fake_spec]

        with patch("silvasonic.controller.worker_evaluator.log") as mock_log:
            specs = await evaluator.evaluate(mock_session)

            # The exception should be caught and logged
            assert len(specs) == 1
            assert specs[0] == fake_spec

            # Log exception should be called once with worker name
            mock_log.exception.assert_called_once_with(
                "worker_evaluator.spec_build_failed", worker="worker_active_error"
            )

    @patch("silvasonic.controller.worker_evaluator.SYSTEM_WORKERS")
    @patch("silvasonic.controller.worker_evaluator.build_worker_spec")
    async def test_evaluate_no_enabled_workers(
        self, mock_build: MagicMock, mock_system_workers: MagicMock, mock_session: AsyncMock
    ) -> None:
        evaluator = SystemWorkerEvaluator()

        w1 = MagicMock()
        w1.name = "worker1"
        mock_system_workers.__iter__.return_value = [w1]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        specs = await evaluator.evaluate(mock_session)

        assert len(specs) == 0
        mock_build.assert_not_called()
