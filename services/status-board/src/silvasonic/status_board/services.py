import logging
from collections.abc import AsyncGenerator
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
                await client.ping()
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
    async def stream_logs(cls, container_id: str) -> AsyncGenerator[str, None]:
        """Stream logs from a specific container."""
        try:
            connector = aiohttp.UnixConnector(path="/run/podman/podman.sock")
            # Podman/Docker log stream format is binary with header, but for text/plain we can often just read chunks
            # if tty=false. If tty=true it is raw.
            # safe bet: stdout=true, stderr=true, follow=true, tail=100
            url = f"http://localhost/containers/{container_id}/logs?stdout=true&stderr=true&follow=true&tail=50"

            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(url) as resp:
                    async for line in resp.content:
                        # Docker stream format: [8 bytes header] [content]
                        # Byte 0: stream type (1=stdout, 2=stderr)
                        # Byte 4-7: length
                        # Minimal parsing to just get text:
                        if len(line) > 8:
                            # We could parse properly, but often for simple display just decoding utf8 works
                            # if we ignore the few binary bytes or if it's raw TTY.
                            # Let's try to just decode and yield.
                            try:
                                # Simple heuristic: if it looks like the header, skip it.
                                # But line buffering might split headers.
                                # For a robust "tail -f" in browser, we just send valid text.
                                yield line.decode("utf-8", errors="replace")
                            except Exception:
                                pass
        except Exception as e:
            yield f"Error streaming logs: {e}\n"
