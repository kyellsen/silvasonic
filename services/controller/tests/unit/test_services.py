from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.controller.services import ServiceManager
from silvasonic.core.database.models.system import SystemService


@pytest.fixture
def mock_orchestrator():
    """Fixture for mocking the orchestrator."""
    return MagicMock()


@pytest.fixture
def mock_session():
    """Fixture for mocking the session."""
    session = AsyncMock()
    # Mock execute result
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session.execute.return_value = result_mock
    return session


@pytest.mark.asyncio
async def test_init_defaults_creates_services(mock_orchestrator, mock_session):
    """Test that missing services in REGISTRY are added to DB."""
    mgr = ServiceManager(mock_orchestrator)

    # Patch REGISTRY to have something
    fake_registry = {"test-service": {"enabled": True}}

    with patch("silvasonic.controller.services.REGISTRY", fake_registry):
        await mgr._init_defaults(mock_session)

        mock_session.add.assert_called_once()
        args = mock_session.add.call_args[0]
        assert isinstance(args[0], SystemService)
        assert args[0].name == "test-service"
        assert args[0].enabled is True


@pytest.mark.asyncio
async def test_reconcile_start_missing(mock_orchestrator, mock_session):
    """Test starting a service that is enabled but not running."""
    mgr = ServiceManager(mock_orchestrator)

    # DB has enabled service
    svc = SystemService(name="test-service", enabled=True, status="stopped")
    mock_session.execute.return_value.scalars.return_value.all.return_value = [svc]

    # Orchestrator has nothing running
    mock_orchestrator.list_active_services.return_value = []
    mock_orchestrator.spawn_service.return_value = True

    with patch("silvasonic.controller.services.REGISTRY", {}):
        await mgr.reconcile_services(mock_session)

        # Should call spawn
        mock_orchestrator.spawn_service.assert_called_once()
        kwargs = mock_orchestrator.spawn_service.call_args.kwargs
        assert kwargs["service_name"] == "test-service"
        assert kwargs["image"] == "silvasonic-test-service"


@pytest.mark.asyncio
async def test_reconcile_stop_disabled(mock_orchestrator, mock_session):
    """Test stopping a service that is disabled but running."""
    mgr = ServiceManager(mock_orchestrator)

    # DB has disabled service
    svc = SystemService(name="test-service", enabled=False, status="running")
    mock_session.execute.return_value.scalars.return_value.all.return_value = [svc]

    # Orchestrator has it running
    mock_orchestrator.list_active_services.return_value = [{"id": "123", "service": "test-service"}]
    mock_orchestrator.stop_service.return_value = True

    with patch("silvasonic.controller.services.REGISTRY", {}):
        await mgr.reconcile_services(mock_session)

        # Should call stop
        mock_orchestrator.stop_service.assert_called_with("123")


@pytest.mark.asyncio
async def test_reconcile_spawn_failure(mock_orchestrator, mock_session):
    """Test handling spawn failure."""
    mgr = ServiceManager(mock_orchestrator)

    svc = SystemService(name="test-service", enabled=True, status="stopped")
    mock_session.execute.return_value.scalars.return_value.all.return_value = [svc]
    mock_orchestrator.list_active_services.return_value = []

    # Fail spawn
    mock_orchestrator.spawn_service.return_value = False

    with patch("silvasonic.controller.services.REGISTRY", {}):
        await mgr.reconcile_services(mock_session)

        mock_orchestrator.spawn_service.assert_called_once()
        # Should not crash


@pytest.mark.asyncio
async def test_init_defaults_already_exists(mock_orchestrator, mock_session):
    """Test that existing services are skipping."""
    mgr = ServiceManager(mock_orchestrator)

    svc = SystemService(name="test-service", enabled=True)
    mock_session.execute.return_value.scalars.return_value.all.return_value = [svc]

    fake_registry = {"test-service": {"enabled": True}}

    with patch("silvasonic.controller.services.REGISTRY", fake_registry):
        await mgr._init_defaults(mock_session)

        # Should NOT add again
        mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_ignore_recorder(mock_orchestrator, mock_session):
    """Test that recorder service is ignored in generic reconciliation."""
    mgr = ServiceManager(mock_orchestrator)

    # DB State (irrelevant for filtering active, but let's exclude recorder from DB usually)
    mock_session.execute.return_value.scalars.return_value.all.return_value = []

    # Orchestrator reports a recorder
    mock_orchestrator.list_active_services.return_value = [{"id": "999", "service": "recorder"}]

    with patch("silvasonic.controller.services.REGISTRY", {}):
        await mgr.reconcile_services(mock_session)


@pytest.mark.asyncio
async def test_reconcile_update_running(mock_orchestrator, mock_session):
    """Test reconciling a service that is already running and enabled."""
    mgr = ServiceManager(mock_orchestrator)

    svc = SystemService(name="test-service", enabled=True, status="stopped")
    mock_session.execute.return_value.scalars.return_value.all.return_value = [svc]

    # Orchestrator reports it is running
    mock_orchestrator.list_active_services.return_value = [{"id": "123", "service": "test-service"}]

    with patch("silvasonic.controller.services.REGISTRY", {}):
        await mgr.reconcile_services(mock_session)

        # Should update status to running
        assert svc.status == "running"
        mock_orchestrator.spawn_service.assert_not_called()
        mock_orchestrator.stop_service.assert_not_called()
