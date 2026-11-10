"""Integration tests for Worker Pull query patterns (ADR-0018).

Validates that the ``recordings`` table partial indices are correctly
used by the query planner and that ``FOR UPDATE SKIP LOCKED`` provides
concurrent claim semantics.

Requires a real PostgreSQL (Testcontainer) instance with the Silvasonic schema.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from silvasonic.core.database.session import _get_engine, _get_session_factory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


def _build_async_url(container: PostgresContainer) -> str:
    """Build an asyncpg connection URL from a testcontainer."""
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    return f"postgresql+asyncpg://silvasonic:silvasonic@{host}:{port}/silvasonic_test"


async def _insert_test_recordings(
    session: AsyncSession, microphone_id: uuid.UUID, count: int = 3
) -> list[uuid.UUID]:
    """Insert test recordings and return their IDs."""
    ids: list[uuid.UUID] = []
    for i in range(count):
        result = await session.execute(
            text("""
                INSERT INTO recordings (
                    started_at, microphone_id, raw_path, processed_path,
                    duration_s, sample_rate_hz, raw_size_bytes, processed_size_bytes
                )
                VALUES (
                    :started_at, :microphone_id, :raw_path, :processed_path,
                    :duration_s, :sample_rate_hz, :raw_size_bytes, :processed_size_bytes
                )
                RETURNING id
            """),
            {
                "started_at": datetime(2026, 1, 1, i, 0, 0, tzinfo=UTC),
                "microphone_id": microphone_id,
                "raw_path": f"/data/recorder/test/raw_{i}.wav",
                "processed_path": f"/data/recorder/test/processed_{i}.wav",
                "duration_s": 30.0,
                "sample_rate_hz": 48000,
                "raw_size_bytes": 2880000,
                "processed_size_bytes": 1440000,
            },
        )
        row = result.fetchone()
        assert row is not None
        ids.append(row[0])
    await session.commit()
    return ids


@pytest.mark.integration
class TestWorkerPullQuery:
    """Verify Worker Pull (ADR-0018) query patterns against real PostgreSQL."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch: pytest.MonkeyPatch, postgres_container: Any) -> None:
        """Inject testcontainer DB credentials into environment."""
        _get_engine.cache_clear()
        _get_session_factory.cache_clear()

        monkeypatch.setenv("SILVASONIC_DB_HOST", postgres_container.get_container_host_ip())
        monkeypatch.setenv("SILVASONIC_DB_PORT", str(postgres_container.get_exposed_port(5432)))
        monkeypatch.setenv("POSTGRES_USER", "silvasonic")
        monkeypatch.setenv("POSTGRES_PASSWORD", "silvasonic")
        monkeypatch.setenv("POSTGRES_DB", "silvasonic_test")

    async def test_for_update_skip_locked(self, postgres_container: PostgresContainer) -> None:
        """Two concurrent sessions claim different rows via SKIP LOCKED."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)

        # Seed a test microphone first
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    INSERT INTO microphones (hardware_id, name, serial_number, model, hardware)
                    VALUES ('test-mic', 'TestMic', 'SN-TEST-001', 'TestMic', '{}')
                    ON CONFLICT (hardware_id) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id
                """)
            )
            microphone_id = result.scalar_one()

        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with session_factory() as session:
            ids = await _insert_test_recordings(session, microphone_id, count=3)
            assert len(ids) == 3

        # Session 1: Lock first available row
        async with session_factory() as s1:
            result1 = await s1.execute(
                text("""
                    SELECT id FROM recordings
                    WHERE deleted_at IS NULL
                    ORDER BY started_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                """)
            )
            row1 = result1.fetchone()
            assert row1 is not None
            locked_id = row1[0]

            # Session 2 (concurrent): Should skip the locked row
            async with session_factory() as s2:
                result2 = await s2.execute(
                    text("""
                        SELECT id FROM recordings
                        WHERE deleted_at IS NULL
                        ORDER BY started_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    """)
                )
                row2 = result2.fetchone()
                assert row2 is not None
                assert row2[0] != locked_id, (
                    "Second session should get a different row (SKIP LOCKED)"
                )

        # Cleanup
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM recordings"))
            await conn.execute(text("DELETE FROM microphones WHERE hardware_id = 'test-mic'"))

        await engine.dispose()

    async def test_partial_index_analysis_pending_used(
        self, postgres_container: PostgresContainer
    ) -> None:
        """EXPLAIN confirms ix_recordings_analysis_pending is used."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)

        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    EXPLAIN (FORMAT TEXT)
                    SELECT id FROM recordings
                    WHERE deleted_at IS NULL
                    ORDER BY started_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                """)
            )
            plan = "\n".join(row[0] for row in result.fetchall())

        await engine.dispose()
        assert "ix_recordings_analysis_pending" in plan, (
            f"Expected partial index scan, got:\n{plan}"
        )

    async def test_partial_index_upload_pending_used(
        self, postgres_container: PostgresContainer
    ) -> None:
        """EXPLAIN confirms ix_recordings_upload_pending is used."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)

        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    EXPLAIN (FORMAT TEXT)
                    SELECT id FROM recordings
                    WHERE uploaded_at IS NULL AND deleted_at IS NULL
                    ORDER BY started_at ASC
                    LIMIT 1
                """)
            )
            plan = "\n".join(row[0] for row in result.fetchall())

        await engine.dispose()
        assert "ix_recordings_upload_pending" in plan, f"Expected partial index scan, got:\n{plan}"
