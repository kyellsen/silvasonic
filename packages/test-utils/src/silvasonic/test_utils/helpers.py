"""Shared helper utilities for Silvasonic integration and smoke tests.

These are plain functions (not fixtures) that support test setup and
teardown. They are intentionally kept simple and side-effect free.
"""

import time

import httpx
from testcontainers.core.container import DockerContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


def build_postgres_url(container: PostgresContainer, driver: str = "asyncpg") -> str:
    """Build a SQLAlchemy-compatible async Postgres connection URL.

    Args:
        container: A running ``PostgresContainer`` instance.
        driver: The async DB driver to use. Defaults to ``asyncpg``.

    Returns:
        A connection URL string suitable for ``create_async_engine()``.

    Example::

        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
    """
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    user = container.username
    password = container.password
    dbname = container.dbname
    return f"postgresql+{driver}://{user}:{password}@{host}:{port}/{dbname}"


def build_redis_url(container: RedisContainer, db: int = 0) -> str:
    """Build a Redis connection URL from a running RedisContainer.

    Args:
        container: A running ``RedisContainer`` instance.
        db: The Redis database number. Defaults to ``0``.

    Returns:
        A connection URL string suitable for ``redis.asyncio.Redis.from_url()``.

    Example::

        url = build_redis_url(redis_container)
        redis = Redis.from_url(url)
    """
    host = container.get_container_host_ip()
    port = container.get_exposed_port(6379)
    return f"redis://{host}:{port}/{db}"


def wait_for_http(
    host: str,
    port: int,
    path: str = "/healthy",
    timeout: float = 60.0,
) -> None:
    """Poll an HTTP endpoint until it returns 200 or the timeout expires.

    Used to wait for a containerised HTTP service to become ready before
    running tests against it.

    Args:
        host: Hostname or IP of the service.
        port: Port number.
        path: URL path to poll. Defaults to ``/healthy``.
        timeout: Maximum seconds to wait. Defaults to 60.

    Raises:
        TimeoutError: If the service does not respond within ``timeout`` seconds.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"http://{host}:{port}{path}", timeout=3.0)
            if resp.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    msg = f"Service on {host}:{port}{path} did not become healthy within {timeout}s"
    raise TimeoutError(msg)


def wait_for_log(
    container: DockerContainer,
    message: str,
    timeout: float = 60.0,
    poll_interval: float = 0.5,
) -> None:
    """Wait for a specific log message to appear in container stdout/stderr.

    Useful for waiting on containers that do not expose an HTTP health endpoint
    (e.g. databases printing "ready to accept connections").

    Args:
        container: A ``testcontainers`` ``DockerContainer`` instance.
        message: The substring to wait for in combined stdout + stderr.
        timeout: Maximum seconds to wait. Defaults to 60.
        poll_interval: Seconds between log polls. Defaults to 0.5.

    Raises:
        TimeoutError: If the message does not appear within ``timeout`` seconds.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        stdout, stderr = container.get_logs()
        logs = (stdout or b"").decode(errors="replace") + (stderr or b"").decode(errors="replace")
        if message in logs:
            return
        time.sleep(poll_interval)
    msg = f"Log message '{message}' not found within {timeout}s"
    raise TimeoutError(msg)


async def clean_database(container: PostgresContainer) -> None:
    """Connect via asyncpg and dynamically TRUNCATE all public tables.

    Queries ``pg_tables`` for all tables in the ``public`` schema (excluding
    TimescaleDB internals like ``_timescale%``) and truncates them using
    ``RESTART IDENTITY CASCADE``.

    This ensures complete data removal between tests in a parallel-safe way
    (when tests share a container per xdist worker) without the need to
    maintain hardcoded tables lists or manage foreign-key constraints.

    Args:
        container: A running ``PostgresContainer`` instance.
    """
    import asyncpg  # type: ignore[import-untyped]

    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(5432))
    conn = await asyncpg.connect(
        host=host,
        port=port,
        user="silvasonic",
        password="silvasonic",
        database="silvasonic_test",
    )
    try:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename NOT LIKE '\\_timescale%'"
        )
        tables = [f'"{row["tablename"]}"' for row in rows]
        if tables:
            # A single TRUNCATE with CASCADE is faster and handles FK dependencies
            query = f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"
            await conn.execute(query)
    finally:
        await conn.close()
