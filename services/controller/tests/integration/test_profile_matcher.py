"""Integration tests for ProfileMatcher against real DB.

Verifies profile scoring and auto-enrollment logic using a real
database, avoiding brittle Mock cascades for SQLAlchemy sessions.
"""

from __future__ import annotations

from typing import Any

import pytest
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.controller.profile_matcher import ProfileMatcher
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.models.system import SystemConfig
from silvasonic.test_utils.helpers import build_postgres_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
]


@pytest.fixture
def session_factory(postgres_container: PostgresContainer) -> async_sessionmaker[AsyncSession]:
    url = build_postgres_url(postgres_container)
    engine = create_async_engine(url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def device_info() -> DeviceInfo:
    return DeviceInfo(
        alsa_card_index=2,
        alsa_name="UltraMic 384K",
        alsa_device="hw:2,0",
        usb_vendor_id="16d0",
        usb_product_id="0b40",
    )


async def seed_profile(
    session: AsyncSession, slug: str, match_config: dict[str, Any]
) -> MicrophoneProfile:
    """Helper to seed a profile."""
    profile = MicrophoneProfile(
        slug=slug, name="Test Profile", config={"audio": {"match": match_config}}
    )
    session.add(profile)
    return profile


async def seed_auto_enrollment(session: AsyncSession, enabled: bool) -> None:
    """Helper to seed auto_enrollment config."""
    config = SystemConfig(key="system", value={"auto_enrollment": enabled})
    session.add(config)


class TestProfileMatcher:
    """Tests for ProfileMatcher scoring and auto-enrollment."""

    async def test_exact_usb_match_score_100(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """Exact USB VID+PID match -> score 100."""
        async with session_factory() as session:
            await seed_profile(
                session, "ultramic_384_evo", {"usb_vendor_id": "16d0", "usb_product_id": "0b40"}
            )
            await seed_auto_enrollment(session, True)
            await session.commit()

        matcher = ProfileMatcher()
        async with session_factory() as session:
            result = await matcher.match(device_info, session)

        assert result.score == 100
        assert result.profile_slug == "ultramic_384_evo"
        assert result.auto_enroll is True

    async def test_alsa_name_match_score_50(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """ALSA name substring match -> score 50."""
        async with session_factory() as session:
            await seed_profile(session, "generic_ultra", {"alsa_name_contains": "UltraMic"})
            await session.commit()

        matcher = ProfileMatcher()
        async with session_factory() as session:
            result = await matcher.match(device_info, session)

        assert result.score == 50
        assert result.profile_slug == "generic_ultra"
        assert result.auto_enroll is False

    async def test_no_match_score_0_no_fallback(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """No matching profile and no generic_usb fallback -> score 0."""
        async with session_factory() as session:
            await seed_profile(
                session, "other_mic", {"usb_vendor_id": "aaaa", "usb_product_id": "bbbb"}
            )
            await session.commit()

        matcher = ProfileMatcher()
        async with session_factory() as session:
            result = await matcher.match(device_info, session)

        assert result.score == 0
        assert result.profile_slug is None
        assert result.auto_enroll is False

    async def test_score_0_fallback_assigns_generic_usb(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """Score 0 + generic_usb in DB -> auto-assign generic_usb."""
        async with session_factory() as session:
            await seed_profile(
                session, "other_mic", {"usb_vendor_id": "aaaa", "usb_product_id": "bbbb"}
            )
            await seed_profile(session, "generic_usb", {})  # generic_usb fallback
            await seed_auto_enrollment(session, True)
            await session.commit()

        matcher = ProfileMatcher()
        async with session_factory() as session:
            result = await matcher.match(device_info, session)

        assert result.score == 0
        assert result.profile_slug == "generic_usb"
        assert result.auto_enroll is True

    async def test_auto_enrollment_false(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """auto_enrollment=false in system_config -> no auto-enroll even with score 100."""
        async with session_factory() as session:
            await seed_profile(
                session, "ultramic_384_evo", {"usb_vendor_id": "16d0", "usb_product_id": "0b40"}
            )
            await seed_auto_enrollment(session, False)
            await session.commit()

        matcher = ProfileMatcher()
        async with session_factory() as session:
            result = await matcher.match(device_info, session)

        assert result.score == 100
        assert result.auto_enroll is False

    async def test_usb_match_case_insensitive(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """USB VID/PID match is case-insensitive."""
        async with session_factory() as session:
            await seed_profile(
                session, "ultramic", {"usb_vendor_id": "16D0", "usb_product_id": "0B40"}
            )
            await seed_auto_enrollment(session, True)
            await session.commit()

        matcher = ProfileMatcher()
        async with session_factory() as session:
            result = await matcher.match(device_info, session)

        assert result.score == 100
        assert result.profile_slug == "ultramic"

    async def test_profile_without_match_criteria(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Profile with empty config -> score 0."""
        async with session_factory() as session:
            await seed_profile(session, "bare_profile", {})
            await session.commit()

        info = DeviceInfo(alsa_card_index=0, alsa_name="Any", alsa_device="hw:0,0")
        matcher = ProfileMatcher()
        async with session_factory() as session:
            result = await matcher.match(info, session)

        assert result.score == 0
        assert result.profile_slug is None
