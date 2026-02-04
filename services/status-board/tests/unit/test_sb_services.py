import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from silvasonic.status_board.services import ContainerService, StatusService


@pytest.mark.asyncio
async def test_check_database_success() -> None:
    """Test successful database connection check."""
    with patch("silvasonic.status_board.services.engine") as mock_engine:
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn

        result = await StatusService.check_database()

        assert result["status"] == "connected"
        mock_conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_check_database_failure() -> None:
    """Test failure handling in database connection check."""
    with patch("silvasonic.status_board.services.engine") as mock_engine:
        mock_engine.connect.side_effect = Exception("DB Error")
        result = await StatusService.check_database()
        assert result["status"] == "error"
        assert "DB Error" in result["error"]


@pytest.mark.asyncio
async def test_check_redis_success() -> None:
    """Test successful Redis connection check."""
    with patch("silvasonic.status_board.services.get_redis_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value.__aenter__.return_value = mock_client

        mock_client.info.return_value = {"redis_version": "7.0"}
        mock_client.connection_pool.connection_kwargs = {"host": "localhost"}

        result = await StatusService.check_redis()

        assert result["status"] == "connected"
        assert result["version"] == "7.0"
        mock_client.ping.assert_called_once()
        mock_client.info.assert_called_once()


@pytest.mark.asyncio
async def test_check_redis_failure() -> None:
    """Test failure handling in Redis connection check."""
    with patch(
        "silvasonic.status_board.services.get_redis_client", side_effect=Exception("Redis Error")
    ):
        result = await StatusService.check_redis()
        assert result["status"] == "error"
        assert "Redis Error" in result["error"]


@pytest.mark.asyncio
async def test_get_containers_success() -> None:
    """Test successful container retrieval."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json.return_value = [{"Id": "123", "Names": ["/test"]}]

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value = mock_response

        containers = await ContainerService.get_containers()

        assert len(containers) == 1
        assert containers[0]["Id"] == "123"


@pytest.mark.asyncio
async def test_get_containers_failure() -> None:
    """Test failure handling in container retrieval."""
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Net Error")):
        containers = await ContainerService.get_containers()
        assert containers == []


@pytest.mark.asyncio
async def test_get_containers_non_200() -> None:
    """Test handling of non-200 response in container retrieval."""
    mock_response = AsyncMock()
    mock_response.status = 500

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value = mock_response
        containers = await ContainerService.get_containers()
        assert containers == []


@pytest.mark.asyncio
async def test_get_recorders() -> None:
    """Test retrieval of recorder containers."""
    # Mock get_containers called inside get_recorders using patch.object
    from silvasonic.status_board.services import ContainerService

    with patch.object(ContainerService, "get_containers", new_callable=AsyncMock) as mock_get_cons:
        mock_get_cons.return_value = [
            {
                "Id": "rec1_long_id",
                "Names": ["/silvasonic-recorder-1"],
                "Image": "silvasonic-recorder:latest",
                "State": "running",
                "NetworkSettings": {"Networks": {"silvasonic_net": {"IPAddress": "10.0.0.5"}}},
            },
            {"Id": "other", "Names": ["/other"], "Image": "redis", "State": "running"},
        ]

        # Mock tcp check
        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            # First call succeeds
            mock_reader = AsyncMock()
            mock_writer = AsyncMock()
            mock_writer.close = Mock()
            mock_conn.return_value = (mock_reader, mock_writer)

            recorders = await ContainerService.get_recorders()

            assert len(recorders) == 1
            assert recorders[0]["id"] == "rec1_long_id"[:12]
            assert recorders[0]["status"] == "online"
            mock_conn.assert_called_with("10.0.0.5", 8000)


@pytest.mark.asyncio
async def test_get_recorders_offline() -> None:
    """Test retrieval of offline recorder containers."""
    from silvasonic.status_board.services import ContainerService

    with patch.object(ContainerService, "get_containers", new_callable=AsyncMock) as mock_get_cons:
        mock_get_cons.return_value = [
            {
                "Id": "rec1",
                "Names": ["/silvasonic-recorder-1"],
                "Image": "silvasonic-recorder",
                "State": "running",
            }
        ]

        with patch("asyncio.open_connection", side_effect=Exception("Conn Refused")):
            recorders = await ContainerService.get_recorders()
            assert len(recorders) == 1
            assert recorders[0]["status"] == "offline"


@pytest.mark.asyncio
async def test_stream_logs() -> None:
    """Test successful log streaming from container."""
    mock_response = AsyncMock()
    mock_response.content = AsyncMock()

    # Setup side_effect for readexactly calls
    # Sequence: Header1(8), Body1(5), Header2(8), Body2(6), Header3(8)->EOF
    mock_response.content.readexactly.side_effect = [
        b"\x01\x00\x00\x00\x00\x00\x00\x05",
        b"Hello",
        b"\x02\x00\x00\x00\x00\x00\x00\x06",
        b"Errors",
        asyncio.IncompleteReadError(b"", 8),
    ]

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value = mock_response

        logs = []
        async for line in ContainerService.stream_logs("123"):
            logs.append(line)

        assert "Hello" in logs[0]
        assert "Errors" in logs[1]


@pytest.mark.asyncio
async def test_stream_logs_error() -> None:
    """Test failure handling during log streaming."""
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Log Error")):
        logs = []
        async for line in ContainerService.stream_logs("123"):
            logs.append(line)

        assert "Error streaming logs" in logs[0]


@pytest.mark.asyncio
async def test_stream_logs_decode_error() -> None:
    """Test decode error handling during log streaming."""
    mock_response = AsyncMock()
    mock_response.content = AsyncMock()

    # Header claiming 5 bytes
    header = b"\x01\x00\x00\x00\x00\x00\x00\x05"
    # 5 bytes of invalid utf-8
    bad_body = b"\xff\xff\xff\xff\xff"

    mock_response.content.readexactly.side_effect = [
        header,
        bad_body,
        asyncio.IncompleteReadError(b"", 8),
    ]

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value = mock_response

        logs = []
        async for line in ContainerService.stream_logs("123"):
            logs.append(line)

        assert "\ufffd" in logs[0]
