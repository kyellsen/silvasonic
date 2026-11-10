"""Integration tests for microphone_repository against a real DB.

Verifies upsert_microphone behavior without needing deep SQLAlchemy mocks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.controller.microphone_repository import upsert_microphone
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.models.system import Microphone
from silvasonic.core.database.session import create_station_engine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
]


_MOCK_VID = "16d0"
_MOCK_PID = "0b40"


@pytest.fixture
def session_factory(station_db: Path) -> async_sessionmaker[AsyncSession]:
    engine = create_station_engine(station_db)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def device_info() -> DeviceInfo:
    return DeviceInfo(
        alsa_card_index=2,
        alsa_name="UltraMic 384K",
        alsa_device="hw:2,0",
        usb_vendor_id=_MOCK_VID,
        usb_product_id=_MOCK_PID,
        usb_serial="ABC123",
    )


class TestUpsertMicrophone:
    """Tests for the upsert_microphone function with real DB session."""

    async def test_upsert_creates_new_microphone(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """New microphone is inserted into DB with a UUIDv7 id from the database."""
        async with session_factory() as session:
            microphone = await upsert_microphone(device_info, session)
            await session.commit()

        assert microphone.hardware_id == f"{_MOCK_VID}-{_MOCK_PID}-ABC123"
        assert microphone.connection_state == "connected"
        assert microphone.enrollment_state == "pending"
        assert microphone.name == "UltraMic 384K"
        assert microphone.first_seen_at is not None

        # Verify it exists in DB, keyed by a database-generated UUIDv7
        assert microphone.id is not None
        assert microphone.id.version == 7
        async with session_factory() as session:
            db_mic = await session.get(Microphone, microphone.id)
            assert db_mic is not None
            assert db_mic.model == "UltraMic 384K"
            assert db_mic.first_seen_at == db_mic.last_seen_at

    async def test_upsert_updates_existing_device(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """Known microphone gets connection_state=connected and updated hardware facts."""
        # 1. First insert
        async with session_factory() as session:
            first = await upsert_microphone(device_info, session)
            await session.commit()
        first_seen_at = first.first_seen_at
        first_id = first.id

        # 2. Modify device_info to simulate hardware drift
        device_info.alsa_card_index = 3
        device_info.alsa_device = "hw:3,0"
        device_info.alsa_name = "UltraMic 384K (Updated)"
        device_info.usb_bus_path = "1-4.1"

        async with session_factory() as session:
            microphone = await upsert_microphone(device_info, session)
            await session.commit()

        assert microphone.connection_state == "connected"
        assert microphone.last_seen_at is not None
        assert microphone.model == "UltraMic 384K (Updated)"
        assert microphone.hardware["alsa_card_index"] == 3
        assert microphone.hardware["alsa_device"] == "hw:3,0"
        assert microphone.hardware["alsa_name"] == "UltraMic 384K (Updated)"
        assert microphone.hardware["usb_bus_path"] == "1-4.1"
        assert microphone.hardware["usb_vendor_id"] == _MOCK_VID
        # Identity, label and first sighting survive the update
        assert microphone.id == first_id
        assert microphone.name == "UltraMic 384K"
        assert microphone.first_seen_at == first_seen_at

        # Ensure no duplicates were made
        async with session_factory() as session:
            result = await session.execute(select(Microphone))
            all_microphones = list(result.scalars().all())
            assert len(all_microphones) == 1

    async def test_upsert_assigns_profile_to_new_device(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """Profile slug is assigned when the microphone is new and auto-enroll."""
        async with session_factory() as session:
            session.add(MicrophoneProfile(slug="ultramic_384_evo", name="Test Profile", config={}))
            microphone = await upsert_microphone(
                device_info, session, profile_slug="ultramic_384_evo", enrollment_state="enrolled"
            )
            await session.commit()

        assert microphone.profile_slug == "ultramic_384_evo"
        assert microphone.enrollment_state == "enrolled"

    async def test_upsert_keeps_existing_profile(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """Existing profile slug is not overwritten."""
        # 1. Insert with custom profile
        async with session_factory() as session:
            session.add(MicrophoneProfile(slug="custom_profile", name="Custom Profile", config={}))
            session.add(MicrophoneProfile(slug="ultramic_384_evo", name="Test Profile", config={}))
            await upsert_microphone(
                device_info, session, profile_slug="custom_profile", enrollment_state="enrolled"
            )
            await session.commit()

        # 2. Upsert again with new detected profile slug
        async with session_factory() as session:
            microphone = await upsert_microphone(
                device_info, session, profile_slug="ultramic_384_evo"
            )
            await session.commit()

        # Should NOT overwrite existing profile
        assert microphone.profile_slug == "custom_profile"
