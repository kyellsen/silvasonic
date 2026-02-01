import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable
from typing import Any, cast

import aiohttp
from silvasonic.core.database.session import engine
from silvasonic.core.redis.client import get_redis_client
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

    SOCKET_PATH = "unix:///run/podman/podman.sock"

    @classmethod
    async def get_containers(cls) -> list[dict[str, Any]]:
        """List all containers."""
        try:
            connector = aiohttp.UnixConnector(path="/run/podman/podman.sock")
            async with aiohttp.ClientSession(connector=connector) as session:
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
    async def get_recorders(cls) -> list[dict[str, Any]]:
        """Find and check all running recorder containers."""
        containers = await cls.get_containers()
        recorders = []
        for c in containers:
            # Check if image name contains 'recorder'
            image = c.get("Image", "")
            state = c.get("State", "")

            # Filter for running recorders
            if "silvasonic-recorder" in image and state == "running":
                # Extract IP from NetworkSettings
                # structure: NetworkSettings -> Networks -> <network_name> -> IPAddress
                ip = "127.0.0.1"  # Fallback
                networks = c.get("NetworkSettings", {}).get("Networks", {})
                for _, net_info in networks.items():
                    if net_info.get("IPAddress"):
                        ip = net_info.get("IPAddress")
                        break

                # Check port 8000 connectivity
                is_online = False
                try:
                    # Simple TCP check to the container IP:8000
                    # Since we are in the same network (silvasonic-net), we can reach it by IP
                    reader, writer = await asyncio.open_connection(ip, 8000)
                    writer.close()
                    await writer.wait_closed()
                    is_online = True
                except Exception:
                    is_online = False

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
            connector = aiohttp.UnixConnector(path="/run/podman/podman.sock")
            # we remove tail limit to get full logs from start
            url = f"http://localhost/containers/{container_id}/logs?stdout=true&stderr=true&follow=true"

            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(url) as resp:
                    # Docker log stream format: [8 bytes header] [content]
                    # Header:
                    #   Byte 0: stream type (1=stdout, 2=stderr)
                    #   Byte 1-3: padding
                    #   Byte 4-7: payload length (big endian)
                    while True:
                        try:
                            header = await resp.content.readexactly(8)
                        except asyncio.IncompleteReadError:
                            break

                        # Parse length
                        # The header is: [stream_type 1b] [padding 3b] [length 4b]
                        payload_len = int.from_bytes(header[4:8], byteorder="big")

                        if payload_len > 0:
                            try:
                                payload = await resp.content.readexactly(payload_len)
                            except asyncio.IncompleteReadError:
                                break

                            # Clean up the payload - it might contain multiple lines
                            # We decode and split by lines to yield them properly to SSE
                            chunk_text = payload.decode("utf-8", errors="replace")

                            # We might want to yield line by line for SSE
                            for line in chunk_text.splitlines():
                                yield line

        except Exception as e:
            yield f"Error streaming logs: {e}\n"
