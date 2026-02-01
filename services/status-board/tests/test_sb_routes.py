from collections.abc import AsyncGenerator, Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from silvasonic.status_board.main import app

client = TestClient(app)


@pytest.fixture
def mock_check_db() -> Iterator[AsyncMock]:
    """Mock database check service."""
    with patch(
        "silvasonic.status_board.services.StatusService.check_database", new_callable=AsyncMock
    ) as m:
        m.return_value = {"status": "connected", "host": "localhost"}
        yield m


@pytest.fixture
def mock_check_redis() -> Iterator[AsyncMock]:
    """Mock Redis check service."""
    with patch(
        "silvasonic.status_board.services.StatusService.check_redis", new_callable=AsyncMock
    ) as m:
        m.return_value = {"status": "connected", "version": "7.0"}
        yield m


@pytest.fixture
def mock_get_containers() -> Iterator[AsyncMock]:
    """Mock container retrieval service."""
    with patch(
        "silvasonic.status_board.services.ContainerService.get_containers", new_callable=AsyncMock
    ) as m:
        m.return_value = [
            {"Id": "c1", "Names": ["/silvasonic-recorder"], "State": "running"},
            {"Id": "c2", "Names": ["/silvasonic-database"], "State": "running"},
        ]
        yield m


@pytest.fixture
def mock_get_recorders() -> Iterator[AsyncMock]:
    """Mock recorder retrieval service."""
    # Use patch object on the class to be sure
    from silvasonic.status_board.services import ContainerService

    with patch.object(ContainerService, "get_recorders", new_callable=AsyncMock) as m:
        m.return_value = [
            {
                "id": "c1",
                "full_id": "c1_full",
                "name": "silvasonic-recorder",
                "ip": "127.0.0.1",
                "status": "online",
            }
        ]
        yield m


def test_workspace(mock_get_recorders: AsyncMock) -> None:
    """Test workspace endpoint availability."""
    response = client.get("/workspace")
    assert response.status_code == 200
    assert "Silvasonic Dev Status" in response.text
    # Verify recorder is listed in sidebar
    assert "silvasonic-recorder" in response.text


def test_dashboard(
    mock_check_db: AsyncMock, mock_check_redis: AsyncMock, mock_get_containers: AsyncMock
) -> None:
    """Test dashboard endpoint with mocked services."""
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "connected" in response.text


def test_service_detail_found(mock_get_containers: AsyncMock) -> None:
    """Test retrieving details for an existing service."""
    response = client.get("/services/database")
    assert response.status_code == 200
    # Template renders "database" not "silvasonic-database"
    assert "database" in response.text
    assert "c2" in response.text


def test_service_detail_not_found(mock_get_containers: AsyncMock) -> None:
    """Test retrieving details for a non-existent service."""
    response = client.get("/services/unknown")
    assert response.status_code == 404


def test_service_logs_found(mock_get_containers: AsyncMock) -> None:
    """Test retrieving logs for an existing service."""
    response = client.get("/services/database/logs")
    assert response.status_code == 200


def test_service_logs_not_found(mock_get_containers: AsyncMock) -> None:
    """Test retrieving logs for a non-existent service."""
    response = client.get("/services/unknown/logs")
    assert response.status_code == 404


def test_list_recorders(mock_get_recorders: AsyncMock) -> None:
    """Test listing recorder services."""
    response = client.get("/services/recorders")
    assert response.status_code == 200
    assert "silvasonic-recorder" in response.text


def test_recorder_detail_found(mock_get_recorders: AsyncMock) -> None:
    """Test retrieving details for an existing recorder."""
    response = client.get("/services/recorders/c1")
    assert response.status_code == 200
    assert "c1_full" in response.text


def test_recorder_detail_not_found(mock_get_recorders: AsyncMock) -> None:
    """Test retrieving details for a non-existent recorder."""
    response = client.get("/services/recorders/unknown")
    assert response.status_code == 404


def test_health() -> None:
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "System Operational" in response.text


def test_view_logs() -> None:
    """Test generic log view endpoint."""
    response = client.get("/logs/c1")
    assert response.status_code == 200
    assert "c1" in response.text


@pytest.mark.asyncio
async def test_stream_logs_endpoint() -> None:
    """Test log streaming endpoint."""

    # Mock services.ContainerService.stream_logs to return a generator
    async def mock_gen(cid: str) -> AsyncGenerator[str, None]:
        yield "Line 1"
        yield "Line 2"

    with patch(
        "silvasonic.status_board.services.ContainerService.stream_logs", side_effect=mock_gen
    ):
        response = client.get("/stream/c1")
        assert response.status_code == 200
        assert "data: Line 1" in response.text


def test_controller_detail_found(mock_get_containers: AsyncMock) -> None:
    """Test retrieving details for the controller service."""
    # Add controller to the mock
    mock_get_containers.return_value.append(
        {"Id": "c3", "Names": ["/silvasonic-controller"], "State": "running"}
    )

    response = client.get("/services/controller")
    assert response.status_code == 200
    assert "controller" in response.text
    assert "c3" in response.text
