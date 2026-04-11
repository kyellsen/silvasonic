from unittest.mock import AsyncMock, MagicMock

import pytest
from silvasonic.controller.device_repository import upsert_device
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.core.database.models.system import Device


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    # add() is synchronous in SQLAlchemy, so we use MagicMock
    session.add = MagicMock()
    return session


@pytest.fixture
def sample_device_info() -> DeviceInfo:
    return DeviceInfo(
        alsa_card_index=2,
        alsa_device="hw:2,0",
        alsa_name="UltraMic",
        usb_vendor_id="1234",
        usb_product_id="5678",
        usb_serial="999",
        usb_bus_path="1-1",
    )


@pytest.mark.asyncio
@pytest.mark.unit
class TestDeviceRepositoryUpsert:
    async def test_upsert_new_device(
        self, mock_session: AsyncMock, sample_device_info: DeviceInfo
    ) -> None:
        """Insert a brand new device."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        device = await upsert_device(
            sample_device_info, mock_session, profile_slug="custom", enrollment_status="enrolled"
        )

        # Asserts on the new model creation
        assert device.name == "1234-5678-999"
        assert device.serial_number == "999"
        assert device.model == "UltraMic"
        assert device.status == "online"
        assert device.enrollment_status == "enrolled"
        assert device.profile_slug == "custom"
        assert device.enabled is True

        # Ensure the volatile hardware state is persisted
        assert device.config["alsa_card_index"] == 2
        assert device.config["alsa_device"] == "hw:2,0"
        assert device.config["alsa_name"] == "UltraMic"
        assert device.config["usb_vendor_id"] == "1234"
        assert device.config["usb_product_id"] == "5678"
        assert device.config["usb_serial"] == "999"
        assert device.config["usb_bus_path"] == "1-1"

        # Verify added to session
        mock_session.add.assert_called_once_with(device)

    async def test_upsert_existing_device_preserves_unrelated_config(
        self, mock_session: AsyncMock, sample_device_info: DeviceInfo
    ) -> None:
        """Updates volatile hardware properties while preserving custom JSONB keys."""
        existing_device = Device(
            name="1234-5678-999",
            config={"custom_gain": 42, "alsa_card_index": 1},  # Old hardware state
            profile_slug="old_profile",  # pragma logic integration tested
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_device
        mock_session.execute.return_value = mock_result

        device = await upsert_device(sample_device_info, mock_session)

        # Returns the same tracked instance
        assert device is existing_device

        # Mutated properties
        assert device.status == "online"
        assert device.model == "UltraMic"

        # Verify the volatile hardware mapping bugfix:
        # dict(existing.config) ensures JSONB flush changes, and custom field must remain.
        assert device.config["custom_gain"] == 42

        # New hardware state overrides old state
        assert device.config["alsa_card_index"] == 2
        assert device.config["alsa_device"] == "hw:2,0"

        # Session should implicitly track updates, so add is not called.
        mock_session.add.assert_not_called()

    async def test_upsert_existing_device_empty_config(
        self, mock_session: AsyncMock, sample_device_info: DeviceInfo
    ) -> None:
        """Handles edge case where existing config is None/empty."""
        existing_device = Device(name="1234-5678-999", config=None, profile_slug="old_profile")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_device
        mock_session.execute.return_value = mock_result

        device = await upsert_device(sample_device_info, mock_session)

        # Config should be correctly bootstrapped
        assert device.config["alsa_card_index"] == 2
        assert device.config["usb_vendor_id"] == "1234"
