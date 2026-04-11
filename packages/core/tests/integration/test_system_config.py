"""Integration test for SystemConfig.updated_at onupdate behaviour.

Verifies that modifying a ``system_config`` row via SQLAlchemy
automatically updates the ``updated_at`` timestamp — the foundation
of the Snapshot Refresh staleness check (ADR-0031).

Requires a real PostgreSQL (Testcontainers, via ``postgres_container`` fixture).
"""

import pytest
from silvasonic.core.database.models.system import SystemConfig
from silvasonic.test_utils.helpers import build_postgres_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


@pytest.mark.integration
class TestSystemConfigOnUpdate:
    """Verify that SQLAlchemy's onupdate= triggers on JSONB modifications."""

    async def test_updated_at_changes_on_value_modification(
        self, postgres_container: PostgresContainer
    ) -> None:
        """Modifying a system_config row updates its updated_at timestamp.

        This is the core contract that _refresh_config() relies on:
        if updated_at doesn't change, the staleness check won't detect
        modifications and workers will run with stale configuration.
        """
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Phase 1: Insert a config row
        async with session_factory() as session:
            row = SystemConfig(key="test_onupdate", value={"threshold": 0.5})
            session.add(row)
            await session.commit()
            original_updated_at = row.updated_at

        assert original_updated_at is not None

        # Phase 2: Modify the value (simulate a user changing a threshold)
        async with session_factory() as session:
            found = await session.get(SystemConfig, "test_onupdate")
            assert found is not None
            found.value = {"threshold": 0.8}  # Changed!
            await session.commit()
            new_updated_at = found.updated_at

        # The onupdate= must have fired — timestamp must be newer
        assert new_updated_at is not None
        assert new_updated_at > original_updated_at

        await engine.dispose()
