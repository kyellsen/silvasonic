"""Integration tests for device_repository against a real DB.

Verifies upsert_device behavior without needing deep SQLAlchemy mocks.
"""

from __future__ import annotations

import pytest
from silvasonic.controller.device_repository import upsert_device
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.models.system import Device
from silvasonic.test_utils.helpers import build_postgres_url
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
]


_MOCK_VID = "16d0"
_MOCK_PID = "0b40"


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
        usb_vendor_id=_MOCK_VID,
        usb_product_id=_MOCK_PID,
        usb_serial="ABC123",
    )


class TestUpsertDevice:
    """Tests for the upsert_device function with real DB session."""

    async def test_upsert_creates_new_device(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """New device is inserted into DB."""
        async with session_factory() as session:
            device = await upsert_device(device_info, session)
            await session.commit()

        assert device.name == f"{_MOCK_VID}-{_MOCK_PID}-ABC123"
        assert device.status == "online"
        assert device.enrollment_status == "pending"

        # Verify it exists in DB
        async with session_factory() as session:
            db_device = await session.get(Device, device.name)
            assert db_device is not None
            assert db_device.model == "UltraMic 384K"

    async def test_upsert_updates_existing_device(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """Known device gets status=online and updated config."""
        # 1. First insert
        async with session_factory() as session:
            await upsert_device(device_info, session)
            await session.commit()

        # 2. Modify device_info to simulate hardware drift
        device_info.alsa_card_index = 3
        device_info.alsa_device = "hw:3,0"
        device_info.alsa_name = "UltraMic 384K (Updated)"
        device_info.usb_bus_path = "1-4.1"

        async with session_factory() as session:
            device = await upsert_device(device_info, session)
            await session.commit()

        assert device.status == "online"
        assert device.last_seen is not None
        assert device.model == "UltraMic 384K (Updated)"
        assert device.config["alsa_card_index"] == 3
        assert device.config["alsa_device"] == "hw:3,0"
        assert device.config["alsa_name"] == "UltraMic 384K (Updated)"
        assert device.config["usb_bus_path"] == "1-4.1"
        assert device.config["usb_vendor_id"] == _MOCK_VID

        # Ensure no duplicates were made
        async with session_factory() as session:
            result = await session.execute(select(Device))
            all_devices = list(result.scalars().all())
            assert len(all_devices) == 1

    async def test_upsert_assigns_profile_to_new_device(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """Profile slug is assigned when device is new and auto-enroll."""
        async with session_factory() as session:
            session.add(MicrophoneProfile(slug="ultramic_384_evo", name="Test Profile", config={}))
            device = await upsert_device(
                device_info, session, profile_slug="ultramic_384_evo", enrollment_status="enrolled"
            )
            await session.commit()

        assert device.profile_slug == "ultramic_384_evo"
        assert device.enrollment_status == "enrolled"

    async def test_upsert_keeps_existing_profile(
        self, session_factory: async_sessionmaker[AsyncSession], device_info: DeviceInfo
    ) -> None:
        """Existing profile slug is not overwritten."""
        # 1. Insert with custom profile
        async with session_factory() as session:
            session.add(MicrophoneProfile(slug="custom_profile", name="Custom Profile", config={}))
            session.add(MicrophoneProfile(slug="ultramic_384_evo", name="Test Profile", config={}))
            await upsert_device(
                device_info, session, profile_slug="custom_profile", enrollment_status="enrolled"
            )
            await session.commit()

        # 2. Upsert again with new detected profile slug
        async with session_factory() as session:
            device = await upsert_device(device_info, session, profile_slug="ultramic_384_evo")
            await session.commit()

        # Should NOT overwrite existing profile
        assert device.profile_slug == "custom_profile"
