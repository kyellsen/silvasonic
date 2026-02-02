import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
@pytest.mark.integration
async def test_schema_initialization(postgres_container: str) -> None:
    """Test that the database schema (init.sql) applies correctly."""
    # 1. Locate init.sql
    # tests/integration -> tests -> core -> packages -> silvasonic
    base_dir = os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
    )
    init_sql_path = os.path.join(base_dir, "scripts", "db", "init.sql")

    assert os.path.exists(init_sql_path), f"init.sql not found at {init_sql_path}"

    with open(init_sql_path) as f:
        sql_script = f.read()

    # 2. Connect to the fresh container
    engine = create_async_engine(postgres_container)

    # 3. Apply Schema
    # We must split by statements because some drivers/commands behave better that way,
    # but sqlalchemy execute(text()) might handle multiple statements if supported by driver.
    # Asyncpg usually supports multiple statements in one execute call.
    async with engine.begin() as conn:
        for statement in sql_script.split(";"):
            if statement.strip():
                await conn.execute(text(statement))

    # 4. Verify Tables
    async with engine.connect() as conn:
        # Check standard tables
        result = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        )
        tables = [row[0] for row in result.fetchall()]

        expected_tables = [
            "devices",
            "system_services",
            "system_config",
            "recordings",
            "uploads",
            "detections",
            "weather",
        ]
        for t in expected_tables:
            assert t in tables, f"Table {t} missing from schema"

        # Check Hypertables (TimescaleDB)
        # Note: 'detections' and 'weather' should be hypertables
        result = await conn.execute(
            text("SELECT hypertable_name FROM timescaledb_information.hypertables")
        )
        hypertables = [row[0] for row in result.fetchall()]
        assert "detections" in hypertables
        assert "weather" in hypertables
        assert "recordings" not in hypertables

    await engine.dispose()
