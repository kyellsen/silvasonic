"""Integration tests for Worker Pull query patterns (ADR-0018, ADR-0037).

Validates that a claim — one short ``UPDATE … RETURNING`` transaction —
hands each recording to exactly one worker, and that the query planner
uses the ``recordings`` partial indexes.

Runs against a real station database file (SQLite) with the Silvasonic schema.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from silvasonic.core.database.session import create_station_engine
from silvasonic.core.database.types import to_epoch_us
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

CLAIM = text("""
    UPDATE recordings
    SET analysis_state = json_set(analysis_state, '$.test', 'running')
    WHERE id = (
        SELECT id FROM recordings
        WHERE local_deleted = 0
          AND json_extract(analysis_state, '$.test') IS NULL
        ORDER BY time ASC
        LIMIT 1
    )
    RETURNING id
""")


async def _seed(engine: AsyncEngine, count: int = 3) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                INSERT INTO devices (name, serial_number, model, config)
                VALUES ('test-mic', 'SN-TEST-001', 'TestMic', '{}')
                ON CONFLICT (name) DO NOTHING
            """)
        )
        for i in range(count):
            await conn.execute(
                text("""
                    INSERT INTO recordings (
                        time, sensor_id, file_raw, file_processed,
                        duration, sample_rate, filesize_raw, filesize_processed
                    ) VALUES (
                        :time, 'test-mic', :file_raw, :file_processed,
                        30.0, 48000, 2880000, 1440000
                    )
                """),
                {
                    "time": to_epoch_us(datetime(2026, 1, 1, i, 0, 0, tzinfo=UTC)),
                    "file_raw": f"test/raw_{i}.wav",
                    "file_processed": f"test/processed_{i}.wav",
                },
            )


async def _claim(engine: AsyncEngine) -> int | None:
    async with engine.begin() as conn:
        row = (await conn.execute(CLAIM)).first()
        return None if row is None else int(row[0])


async def _plan(engine: AsyncEngine, sql: str) -> str:
    async with engine.connect() as conn:
        rows = (await conn.execute(text(f"EXPLAIN QUERY PLAN {sql}"))).all()
    return "\n".join(str(row[-1]) for row in rows)


@pytest.mark.integration
class TestWorkerPullQuery:
    """Verify Worker Pull query patterns against a real station database."""

    async def test_concurrent_claims_get_different_rows(self, station_db: Path) -> None:
        """Workers claiming at the same moment never get the same recording."""
        engines = [create_station_engine(station_db) for _ in range(4)]
        await _seed(engines[0], count=3)

        claimed = await asyncio.gather(*(_claim(e) for e in engines))
        for engine in engines:
            await engine.dispose()

        got = [c for c in claimed if c is not None]
        assert len(got) == 3, f"three recordings, three claims: {claimed}"
        assert len(set(got)) == 3, f"a recording was claimed twice: {claimed}"
        assert claimed.count(None) == 1, "the fourth worker finds nothing left"

    async def test_partial_index_analysis_pending_used(self, station_db: Path) -> None:
        """The planner reads pending work through ix_recordings_analysis_pending."""
        engine = create_station_engine(station_db)
        plan = await _plan(
            engine,
            "SELECT id FROM recordings WHERE local_deleted = 0 ORDER BY time ASC LIMIT 1",
        )
        await engine.dispose()
        assert "ix_recordings_analysis_pending" in plan, f"Expected partial index, got:\n{plan}"

    async def test_partial_index_upload_pending_used(self, station_db: Path) -> None:
        """The planner reads the upload queue through ix_recordings_upload_pending."""
        engine = create_station_engine(station_db)
        plan = await _plan(
            engine,
            "SELECT id FROM recordings WHERE uploaded = 0 AND local_deleted = 0 "
            "ORDER BY time ASC LIMIT 1",
        )
        await engine.dispose()
        assert "ix_recordings_upload_pending" in plan, f"Expected partial index, got:\n{plan}"
