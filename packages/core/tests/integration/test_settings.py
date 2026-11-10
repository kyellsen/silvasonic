"""Integration tests for SettingsSection.updated_at and revision.

Verifies that modifying a ``settings`` row via SQLAlchemy
automatically updates the ``updated_at`` timestamp — the foundation
of the Snapshot Refresh staleness check (ADR-0031).

Requires a real PostgreSQL (Testcontainers, via ``postgres_container`` fixture).
"""

import pytest
from silvasonic.core.database.models.system import SettingsSection
from silvasonic.test_utils.helpers import build_postgres_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


@pytest.mark.integration
class TestSettingsSectionOnUpdate:
    """Verify that SQLAlchemy's onupdate= triggers on JSONB modifications."""

    async def test_updated_at_changes_on_value_modification(
        self, postgres_container: PostgresContainer
    ) -> None:
        """Modifying a settings row updates its updated_at timestamp.

        This is the core contract that _refresh_config() relies on:
        if updated_at doesn't change, the staleness check won't detect
        modifications and workers will run with stale configuration.
        """
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Phase 1: Insert a config row
        async with session_factory() as session:
            row = SettingsSection(section="test_onupdate", value={"threshold": 0.5})
            session.add(row)
            await session.commit()
            original_updated_at = row.updated_at

        assert original_updated_at is not None

        # Phase 2: Modify the value (simulate a user changing a threshold)
        async with session_factory() as session:
            found = await session.get(SettingsSection, "test_onupdate")
            assert found is not None
            found.value = {"threshold": 0.8}  # Changed!
            await session.commit()
            new_updated_at = found.updated_at

        # The onupdate= must have fired — timestamp must be newer
        assert new_updated_at is not None
        assert new_updated_at > original_updated_at

        await engine.dispose()


@pytest.mark.integration
class TestSettingsRevision:
    """The settings trigger bumps revision on every write (backs If-Match)."""

    async def test_revision_starts_at_one_and_increments(
        self, postgres_container: PostgresContainer
    ) -> None:
        """Revision is 1 on insert and grows by one with each UPDATE."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with session_factory() as session:
            session.add(SettingsSection(section="test_revision", value={"a": 1}))
            await session.commit()

        async def revision() -> int:
            async with session_factory() as session:
                result = await session.execute(
                    text("SELECT revision FROM settings WHERE section = 'test_revision'")
                )
                return int(result.scalar_one())

        assert await revision() == 1

        # ORM write
        async with session_factory() as session:
            found = await session.get(SettingsSection, "test_revision")
            assert found is not None
            found.value = {"a": 2}
            await session.commit()
        assert await revision() == 2

        # Raw SQL write, even one that sets revision itself
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE settings SET value = '{\"a\": 3}'::jsonb, revision = 99 "
                    "WHERE section = 'test_revision'"
                )
            )
            await session.commit()
        assert await revision() == 3

        await engine.dispose()
