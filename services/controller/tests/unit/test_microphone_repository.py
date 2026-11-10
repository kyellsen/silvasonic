from unittest.mock import AsyncMock, MagicMock

import pytest
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.controller.microphone_repository import upsert_microphone
from silvasonic.core.database.models.system import Microphone


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
class TestMicrophoneRepositoryUpsert:
    async def test_upsert_new_microphone(
        self, mock_session: AsyncMock, sample_device_info: DeviceInfo
    ) -> None:
        """Insert a brand new microphone."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        microphone = await upsert_microphone(
            sample_device_info, mock_session, profile_slug="custom", enrollment_state="enrolled"
        )

        # Asserts on the new model creation
        assert microphone.hardware_id == "1234-5678-999"
        assert microphone.serial_number == "999"
        assert microphone.model == "UltraMic"
        assert microphone.connection_state == "connected"
        assert microphone.enrollment_state == "enrolled"
        assert microphone.profile_slug == "custom"
        assert microphone.enabled is True

        # The user label starts as the model; first and last sighting are now
        assert microphone.name == "UltraMic"
        assert microphone.first_seen_at is not None
        assert microphone.last_seen_at == microphone.first_seen_at

        # Ensure the volatile hardware state is persisted
        assert microphone.hardware["alsa_card_index"] == 2
        assert microphone.hardware["alsa_device"] == "hw:2,0"
        assert microphone.hardware["alsa_name"] == "UltraMic"
        assert microphone.hardware["usb_vendor_id"] == "1234"
        assert microphone.hardware["usb_product_id"] == "5678"
        assert microphone.hardware["usb_serial"] == "999"
        assert microphone.hardware["usb_bus_path"] == "1-1"

        # Verify added to session
        mock_session.add.assert_called_once_with(microphone)

    async def test_upsert_existing_microphone_preserves_unrelated_hardware(
        self, mock_session: AsyncMock, sample_device_info: DeviceInfo
    ) -> None:
        """Updates volatile hardware properties while preserving custom JSONB keys."""
        existing = Microphone(
            hardware_id="1234-5678-999",
            name="Teich",
            hardware={"custom_gain": 42, "alsa_card_index": 1},  # Old hardware state
            profile_slug="old_profile",  # pragma logic integration tested
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result

        microphone = await upsert_microphone(sample_device_info, mock_session)

        # Returns the same tracked instance
        assert microphone is existing

        # Mutated properties
        assert microphone.connection_state == "connected"
        assert microphone.model == "UltraMic"
        assert microphone.last_seen_at is not None

        # The user's label and first sighting are not touched by a rescan
        assert microphone.name == "Teich"
        assert microphone.first_seen_at is None

        # Verify the volatile hardware mapping bugfix:
        # dict(existing.hardware) ensures JSONB flush changes, and custom field must remain.
        assert microphone.hardware["custom_gain"] == 42

        # New hardware state overrides old state
        assert microphone.hardware["alsa_card_index"] == 2
        assert microphone.hardware["alsa_device"] == "hw:2,0"

        # Session should implicitly track updates, so add is not called.
        mock_session.add.assert_not_called()

    async def test_upsert_existing_microphone_empty_hardware(
        self, mock_session: AsyncMock, sample_device_info: DeviceInfo
    ) -> None:
        """Handles edge case where existing hardware facts are None/empty."""
        existing = Microphone(
            hardware_id="1234-5678-999", hardware=None, profile_slug="old_profile"
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result

        microphone = await upsert_microphone(sample_device_info, mock_session)

        # Hardware facts should be correctly bootstrapped
        assert microphone.hardware["alsa_card_index"] == 2
        assert microphone.hardware["usb_vendor_id"] == "1234"
