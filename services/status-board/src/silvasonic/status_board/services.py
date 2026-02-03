import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable
from contextlib import asynccontextmanager
from typing import Any, cast

import aiohttp
from silvasonic.core.database.session import engine
from silvasonic.core.redis.client import get_redis_client
from silvasonic.status_board.config import settings
from sqlalchemy import text

logger = logging.getLogger(__name__)


class StatusService:
    """Service to check the health of infrastructure components."""

    @staticmethod
    async def check_database() -> dict[str, Any]:
        """Check PostgreSQL connection."""
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return {"status": "connected", "host": engine.url.host}
        except Exception as e:
            logger.error(f"Database check failed: {e}")
            return {"status": "error", "error": str(e), "host": engine.url.host}

    @staticmethod
    async def check_redis() -> dict[str, Any]:
        """Check Redis connection."""
        try:
            async with get_redis_client() as client:
                await cast(Awaitable[bool], client.ping())
                info = await client.info()
                host = client.connection_pool.connection_kwargs.get("host", "unknown")
                return {"status": "connected", "host": host, "version": info.get("redis_version")}
        except Exception as e:
            logger.error(f"Redis check failed: {e}")
            return {"status": "error", "error": str(e)}


class ContainerService:
    """Service to interact with the Docker/Podman engine via Unix socket."""

    # Docker Log Header Constants
    # [stream_type 1b] [padding 3b] [length 4b]
    LOG_HEADER_SIZE = 8
    STREAM_TYPE_INDEX = 0
    PAYLOAD_LEN_START = 4
    PAYLOAD_LEN_END = 8

    @classmethod
    @asynccontextmanager
    async def _get_session(cls) -> AsyncGenerator[aiohttp.ClientSession, None]:
        """Provides an aiohttp session configured for the Podman socket."""
        # Check if the socket path is a unix path or http url (though usually unix for podman)
        # For aiohttp, 'unix://' prefix usually needs stripped for UnixConnector if using path argument,
        # but modern aiohttp handles URLs well. However, UnixConnector takes 'path' arg.
        socket_path = settings.PODMAN_SOCKET_PATH
        if socket_path.startswith("unix://"):
            socket_path = socket_path.replace("unix://", "")

        connector = aiohttp.UnixConnector(path=socket_path)
        async with aiohttp.ClientSession(connector=connector) as session:
            yield session

    @classmethod
    async def get_containers(cls) -> list[dict[str, Any]]:
        """List all containers."""
        try:
            async with cls._get_session() as session:
                async with session.get("http://localhost/containers/json?all=true") as resp:
                    if resp.status == 200:
                        return cast(list[dict[str, Any]], await resp.json())
                    else:
                        logger.error(f"Failed to list containers: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"Container service error: {e}")
            return []

    @classmethod
    async def _check_recorder_online(cls, ip: str, port: int = 8000) -> bool:
        """Check if a recorder is reachable via TCP."""
        try:
            reader, writer = await asyncio.open_connection(ip, port)
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    @classmethod
    async def get_recorders(cls) -> list[dict[str, Any]]:
        """Find and check all running recorder containers."""
        containers = await cls.get_containers()
        recorders = []
        for c in containers:
            image = c.get("Image", "")
            state = c.get("State", "")

            if "silvasonic-recorder" in image and state == "running":
                # Extract IP
                ip = "127.0.0.1"
                network_settings = c.get("NetworkSettings") or {}
                networks = network_settings.get("Networks") or {}
                for _, net_info in networks.items():
                    if net_info.get("IPAddress"):
                        ip = net_info.get("IPAddress")
                        break

                is_online = await cls._check_recorder_online(ip)

                container_id = c.get("Id")
                short_id = container_id[:12] if container_id else "unknown"

                recorders.append(
                    {
                        "id": short_id,
                        "full_id": container_id,
                        "name": c.get("Names", ["unknown"])[0].lstrip("/"),
                        "ip": ip,
                        "status": "online" if is_online else "offline",
                        "stream_url": f"http://{ip}:8000/stream.mp3",
                    }
                )
        return recorders

    @classmethod
    async def stream_logs(cls, container_id: str) -> AsyncGenerator[str, None]:
        """Stream logs from a specific container."""
        try:
            # We remove tail limit to get full logs from start
            url = f"http://localhost/containers/{container_id}/logs?stdout=true&stderr=true&follow=true"

            async with cls._get_session() as session:
                async with session.get(url) as resp:
                    while True:
                        try:
                            # Read the Docker multiplexing header
                            header = await resp.content.readexactly(cls.LOG_HEADER_SIZE)
                        except asyncio.IncompleteReadError:
                            break

                        # data_type = header[cls.STREAM_TYPE_INDEX] # 1=stdout, 2=stderr (unused here)
                        payload_len = int.from_bytes(
                            header[cls.PAYLOAD_LEN_START : cls.PAYLOAD_LEN_END], byteorder="big"
                        )

                        if payload_len > 0:
                            try:
                                payload = await resp.content.readexactly(payload_len)
                            except asyncio.IncompleteReadError:
                                break

                            # We decode and split by lines to yield them properly to SSE
                            chunk_text = payload.decode("utf-8", errors="replace")
                            for line in chunk_text.splitlines():
                                yield line

        except Exception as e:
            yield f"Error streaming logs: {e}\n"

    @classmethod
    async def _control_container(cls, container_id: str, action: str) -> bool:
        """Execute start/stop/restart on a container."""
        try:
            url = f"http://localhost/containers/{container_id}/{action}"
            async with cls._get_session() as session:
                async with session.post(url) as resp:
                    if resp.status == 204 or resp.status == 304:
                        return True
                    else:
                        error_text = await resp.text()
                        logger.error(
                            f"Container control {action} failed: {resp.status} - {error_text}"
                        )
                        return False
        except Exception as e:
            logger.error(f"Container control error: {e}")
            return False

    @classmethod
    async def restart_container(cls, container_id: str) -> bool:
        """Restart a container by ID."""
        return await cls._control_container(container_id, "restart")

    @classmethod
    async def stop_container(cls, container_id: str) -> bool:
        """Stop a container by ID."""
        return await cls._control_container(container_id, "stop")

    @classmethod
    async def start_container(cls, container_id: str) -> bool:
        """Start a container by ID."""
        return await cls._control_container(container_id, "start")
