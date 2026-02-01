import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config


@pytest.mark.asyncio
@pytest.mark.integration
async def test_migration_upgrades(postgres_container: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that Alembic migrations run successfully against a real Postgres DB."""
    # Create Alembic configuration
    # We need to point to the alembic.ini file in packages/core
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    alembic_cfg_path = os.path.join(base_dir, "alembic.ini")

    # Verify file exists
    assert os.path.exists(alembic_cfg_path), f"alembic.ini not found at {alembic_cfg_path}"

    alembic_cfg = Config(alembic_cfg_path)

    # Set script_location to absolute path
    # In alembic.ini it is 'migrations', which is relative to alembic.ini location
    migrations_dir = os.path.join(base_dir, "migrations")
    migrations_dir = os.path.join(base_dir, "migrations")
    alembic_cfg.set_main_option("script_location", migrations_dir)
    # Fix deprecation warning by explicit path separator
    alembic_cfg.set_main_option("path_separator", os.pathsep)

    # OVERRIDE the sqlalchemy.url in alembic.ini with our test container URL
    # expected by alembic to be synchronous usually, but asyncpg is also fine for some operations
    # However, Alembic usually needs a sync driver (psycopg2) or special async handling.
    # Our env.py supports async, so passing the async url should work if env.py is set up correctly.
    # Let's see if env.py reads from x_arguments or just config.
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_container)

    # Patch the settings object in silvasonic.core.database.session
    # env.py uses this object to configure the engine, ignoring the url passed in config for async engine
    from urllib.parse import urlparse

    from silvasonic.core.database.session import settings

    url = urlparse(postgres_container)
    monkeypatch.setattr(settings, "POSTGRES_HOST", url.hostname)
    monkeypatch.setattr(settings, "POSTGRES_PORT", url.port)
    monkeypatch.setattr(settings, "POSTGRES_USER", url.username)
    monkeypatch.setattr(settings, "POSTGRES_PASSWORD", url.password)
    monkeypatch.setattr(settings, "POSTGRES_DB", url.path.lstrip("/"))

    # Run the migration
    # Upgrade to head
    # We must run this in a thread because env.py calls asyncio.run(), which fails
    # if called from a thread with a running loop (like our async test).

    try:
        # Run blocking alembic command in a separate thread to avoid asyncio.run() conflict
        # env.py calls asyncio.run(), which fails if called from an existing loop key
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    except Exception as e:
        pytest.fail(f"Alembic upgrade failed: {e}")

    # If we got here, migrations were successful.
    # We could inspect the DB to see if tables were created, but existing Alembic check is a good start.

    # Verify Schema & Hypertables
    # We need to connect to the DB to check metadata
    # We can use the patched settings to get a session/engine, or just use asyncpg/sqlalchemy directly
    # Since we have the `postgres_container` URL, let's use a quick async engine
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(postgres_container)
    async with engine.connect() as conn:
        # Check if tables exist
        result = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        )
        tables = [row[0] for row in result.fetchall()]
        assert "recordings" in tables
        assert "detections" in tables
        assert "weather" in tables

        # Check if they are hypertables
        # The view name might vary by version, but timescaledb_information.hypertables is standard
        result = await conn.execute(
            text("SELECT hypertable_name FROM timescaledb_information.hypertables")
        )
        hypertables = [row[0] for row in result.fetchall()]
        assert "weather" in hypertables
        assert "detections" in hypertables
        assert "recordings" not in hypertables  # Should be standard table now

    await engine.dispose()

    # Downgrade to base (optional, ensures downgrade path works too)
    try:
        await asyncio.to_thread(command.downgrade, alembic_cfg, "base")
    except Exception as e:
        pytest.fail(f"Alembic downgrade failed: {e}")
