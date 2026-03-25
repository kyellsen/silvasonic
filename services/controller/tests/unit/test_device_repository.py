"""Unit tests for device_repository — upsert_device with mock DB session.

All DB dependencies are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from silvasonic.controller.device_repository import upsert_device
from silvasonic.controller.device_scanner import DeviceInfo

# Fictional VID/PID for test isolation (not real hardware).
_MOCK_VID = "16d0"
_MOCK_PID = "0b40"


@pytest.mark.unit
class TestUpsertDevice:
    """Tests for the upsert_device function with mock DB session."""

    @pytest.fixture()
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            alsa_card_index=2,
            alsa_name="UltraMic 384K",
            alsa_device="hw:2,0",
            usb_vendor_id=_MOCK_VID,
            usb_product_id=_MOCK_PID,
            usb_serial="ABC123",
        )

    async def test_upsert_creates_new_device(self, device_info: DeviceInfo) -> None:
        """New device is inserted into DB."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session = AsyncMock(add=MagicMock())
        session.execute.return_value = mock_result

        device = await upsert_device(device_info, session)

        session.add.assert_called_once()
        assert device.name == f"{_MOCK_VID}-{_MOCK_PID}-ABC123"
        assert device.status == "online"
        assert device.enrollment_status == "pending"

    async def test_upsert_updates_existing_device(self, device_info: DeviceInfo) -> None:
        """Known device gets status=online and updated last_seen."""
        existing = MagicMock()
        existing.name = f"{_MOCK_VID}-{_MOCK_PID}-ABC123"
        existing.profile_slug = "ultramic_384_evo"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        session = AsyncMock(add=MagicMock())
        session.execute.return_value = mock_result

        device = await upsert_device(device_info, session)

        assert device.status == "online"
        assert device.last_seen is not None
        session.add.assert_not_called()

    async def test_upsert_assigns_profile_to_new_device(self, device_info: DeviceInfo) -> None:
        """Profile slug is assigned when device is new and auto-enroll."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session = AsyncMock(add=MagicMock())
        session.execute.return_value = mock_result

        device = await upsert_device(
            device_info, session, profile_slug="ultramic_384_evo", enrollment_status="enrolled"
        )

        assert device.profile_slug == "ultramic_384_evo"
        assert device.enrollment_status == "enrolled"

    async def test_upsert_keeps_existing_profile(
        self,
        device_info: DeviceInfo,
    ) -> None:
        """Existing profile slug is not overwritten."""
        existing = MagicMock()
        existing.name = f"{_MOCK_VID}-{_MOCK_PID}-ABC123"
        existing.profile_slug = "custom_profile"  # already assigned

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        session = AsyncMock(add=MagicMock())
        session.execute.return_value = mock_result

        device = await upsert_device(device_info, session, profile_slug="ultramic_384_evo")

        # Should NOT overwrite existing profile
        assert device.profile_slug == "custom_profile"
