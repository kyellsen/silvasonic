"""Unit tests for Phase 4 — DeviceScanner, ProfileMatcher.

All hardware (sysfs, /proc/asound) and DB dependencies are mocked.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.controller.device_scanner import (
    DeviceInfo,
    DeviceScanner,
    parse_asound_cards,
    upsert_device,
)
from silvasonic.controller.profile_matcher import ProfileMatcher


# ===========================================================================
# DeviceInfo — stable_device_id
# ===========================================================================
@pytest.mark.unit
class TestDeviceInfo:
    """Tests for the DeviceInfo model and stable_device_id property."""

    def test_stable_id_with_serial(self) -> None:
        """Full USB identity: vendor-product-serial."""
        info = DeviceInfo(
            alsa_card_index=2,
            alsa_name="UltraMic 384K",
            alsa_device="hw:2,0",
            usb_vendor_id="16d0",
            usb_product_id="0b40",
            usb_serial="ABC123",
            usb_bus_path="1-3.2",
        )
        assert info.stable_device_id == "16d0-0b40-ABC123"

    def test_stable_id_without_serial(self) -> None:
        """No serial → port-bound fallback."""
        info = DeviceInfo(
            alsa_card_index=2,
            alsa_name="UltraMic 384K",
            alsa_device="hw:2,0",
            usb_vendor_id="16d0",
            usb_product_id="0b40",
            usb_serial=None,
            usb_bus_path="1-3.2",
        )
        assert info.stable_device_id == "16d0-0b40-port1-3.2"

    def test_stable_id_fallback(self) -> None:
        """No USB info → ALSA card index fallback."""
        info = DeviceInfo(
            alsa_card_index=5,
            alsa_name="Some Card",
            alsa_device="hw:5,0",
        )
        assert info.stable_device_id == "alsa-card5"

    def test_stable_id_empty_strings(self) -> None:
        """Empty string vendor/product treated as missing → falls through to next level."""
        info = DeviceInfo(
            alsa_card_index=3,
            alsa_name="Card",
            alsa_device="hw:3,0",
            usb_vendor_id="",
            usb_product_id="",
        )
        # Empty strings are falsy → fallback to alsa-card
        assert info.stable_device_id == "alsa-card3"


# ===========================================================================
# parse_asound_cards
# ===========================================================================
@pytest.mark.unit
class TestParseAsoundCards:
    """Tests for /proc/asound/cards parser."""

    def test_parse_single_usb_card(self) -> None:
        """One USB-Audio card is parsed correctly."""
        text = " 2 [UltraMic384K  ]: USB-Audio - UltraMic 384K\n"
        cards = parse_asound_cards(text)
        assert len(cards) == 1
        assert cards[0]["index"] == 2
        assert cards[0]["id"] == "UltraMic384K"
        assert cards[0]["driver"] == "USB-Audio"
        assert cards[0]["name"] == "UltraMic 384K"

    def test_parse_multiple_cards(self) -> None:
        """Multiple cards, mixed drivers."""
        text = (
            " 0 [PCH             ]: HDA-Intel - HDA Intel PCH\n"
            "                      HDA Intel PCH at 0xf7200000 irq 32\n"
            " 1 [HDMI            ]: HDA-Intel - HDA Intel HDMI\n"
            "                      HDA Intel HDMI at 0xf7214000 irq 33\n"
            " 2 [UltraMic384K    ]: USB-Audio - UltraMic 384K\n"
            "                      Dodotronic UltraMic384K at usb-0000:00:14-2\n"
        )
        cards = parse_asound_cards(text)
        assert len(cards) == 3
        assert cards[0]["driver"] == "HDA-Intel"
        assert cards[2]["driver"] == "USB-Audio"

    def test_parse_empty_string(self) -> None:
        """Empty string returns empty list."""
        assert parse_asound_cards("") == []

    def test_parse_indented_description_lines_ignored(self) -> None:
        """Indented continuation lines are not matched."""
        text = (
            " 0 [PCH             ]: HDA-Intel - HDA Intel PCH\n"
            "                      HDA Intel PCH at 0xf7200000 irq 32\n"
        )
        cards = parse_asound_cards(text)
        assert len(cards) == 1


# ===========================================================================
# DeviceScanner
# ===========================================================================
@pytest.mark.unit
class TestDeviceScanner:
    """Tests for the DeviceScanner class."""

    def test_scan_all_with_usb_card(self, tmp_path: Any) -> None:
        """scan_all returns DeviceInfo for USB-Audio cards."""
        from silvasonic.controller.device_scanner import UsbInfo

        cards_file = tmp_path / "cards"
        cards_file.write_text(
            " 0 [PCH             ]: HDA-Intel - HDA Intel PCH\n"
            " 2 [UltraMic384K    ]: USB-Audio - UltraMic 384K\n"
        )

        scanner = DeviceScanner(cards_path=cards_file)

        with patch(
            "silvasonic.controller.device_scanner._get_usb_info_for_card",
            return_value=UsbInfo(
                vendor_id="16d0",
                product_id="0b40",
                serial="ABC",
                bus_path="1-2",
            ),
        ):
            devices = scanner.scan_all()

        assert len(devices) == 1
        assert devices[0].alsa_name == "UltraMic 384K"
        assert devices[0].usb_vendor_id == "16d0"
        assert devices[0].alsa_device == "hw:2,0"

    def test_scan_all_no_usb_cards(self, tmp_path: Any) -> None:
        """scan_all returns empty list when no USB-Audio cards exist."""
        cards_file = tmp_path / "cards"
        cards_file.write_text(" 0 [PCH             ]: HDA-Intel - HDA Intel PCH\n")
        scanner = DeviceScanner(cards_path=cards_file)
        devices = scanner.scan_all()
        assert devices == []

    def test_scan_all_file_not_found(self, tmp_path: Any) -> None:
        """scan_all returns empty list when /proc/asound/cards doesn't exist."""
        scanner = DeviceScanner(cards_path=tmp_path / "nonexistent")
        devices = scanner.scan_all()
        assert devices == []


# ===========================================================================
# upsert_device
# ===========================================================================
@pytest.mark.unit
class TestUpsertDevice:
    """Tests for the upsert_device function with mock DB session."""

    @pytest.fixture()
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            alsa_card_index=2,
            alsa_name="UltraMic 384K",
            alsa_device="hw:2,0",
            usb_vendor_id="16d0",
            usb_product_id="0b40",
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
        assert device.name == "16d0-0b40-ABC123"
        assert device.status == "online"
        assert device.enrollment_status == "pending"

    async def test_upsert_updates_existing_device(self, device_info: DeviceInfo) -> None:
        """Known device gets status=online and updated last_seen."""
        existing = MagicMock()
        existing.name = "16d0-0b40-ABC123"
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
        existing.name = "16d0-0b40-ABC123"
        existing.profile_slug = "custom_profile"  # already assigned

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        session = AsyncMock(add=MagicMock())
        session.execute.return_value = mock_result

        device = await upsert_device(device_info, session, profile_slug="ultramic_384_evo")

        # Should NOT overwrite existing profile
        assert device.profile_slug == "custom_profile"


# ===========================================================================
# ProfileMatcher
# ===========================================================================
@pytest.mark.unit
class TestProfileMatcher:
    """Tests for the ProfileMatcher scoring and auto-enrollment."""

    def _make_profile(
        self,
        slug: str,
        usb_vid: str | None = None,
        usb_pid: str | None = None,
        alsa_name: str | None = None,
    ) -> MagicMock:
        """Helper to create a mock MicrophoneProfile."""
        profile = MagicMock()
        profile.slug = slug
        match: dict[str, str] = {}
        if usb_vid:
            match["usb_vendor_id"] = usb_vid
        if usb_pid:
            match["usb_product_id"] = usb_pid
        if alsa_name:
            match["alsa_name_contains"] = alsa_name
        profile.config = {"audio": {"match": match}} if match else {}
        return profile

    @pytest.fixture()
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            alsa_card_index=2,
            alsa_name="UltraMic 384K",
            alsa_device="hw:2,0",
            usb_vendor_id="16d0",
            usb_product_id="0b40",
        )

    async def test_exact_usb_match_score_100(self, device_info: DeviceInfo) -> None:
        """Exact USB VID+PID match → score 100."""
        profile = self._make_profile("ultramic_384_evo", usb_vid="16d0", usb_pid="0b40")

        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [profile]
        session.execute.return_value = mock_result

        # Mock auto_enrollment config
        config_result = MagicMock()
        config_mock = MagicMock()
        config_mock.value = {"auto_enrollment": True}
        config_result.scalar_one_or_none.return_value = config_mock
        session.execute.side_effect = [mock_result, config_result]

        matcher = ProfileMatcher()
        result = await matcher.match(device_info, session)

        assert result.score == 100
        assert result.profile_slug == "ultramic_384_evo"
        assert result.auto_enroll is True

    async def test_alsa_name_match_score_50(self, device_info: DeviceInfo) -> None:
        """ALSA name substring match → score 50."""
        profile = self._make_profile("generic_ultra", alsa_name="UltraMic")

        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [profile]
        session.execute.return_value = mock_result

        matcher = ProfileMatcher()
        result = await matcher.match(device_info, session)

        assert result.score == 50
        assert result.profile_slug == "generic_ultra"
        assert result.auto_enroll is False  # Only score 100 gets auto_enroll

    async def test_no_match_score_0(self, device_info: DeviceInfo) -> None:
        """No matching profile → score 0."""
        profile = self._make_profile("other_mic", usb_vid="aaaa", usb_pid="bbbb")

        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [profile]
        session.execute.return_value = mock_result

        matcher = ProfileMatcher()
        result = await matcher.match(device_info, session)

        assert result.score == 0
        assert result.profile_slug is None

    async def test_no_profiles_in_db(self, device_info: DeviceInfo) -> None:
        """Empty DB → no match."""
        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        matcher = ProfileMatcher()
        result = await matcher.match(device_info, session)

        assert result.score == 0

    async def test_auto_enrollment_false(self, device_info: DeviceInfo) -> None:
        """auto_enrollment=false in system_config → no auto-enroll even with score 100."""
        profile = self._make_profile("ultramic_384_evo", usb_vid="16d0", usb_pid="0b40")

        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [profile]

        config_result = MagicMock()
        config_mock = MagicMock()
        config_mock.value = {"auto_enrollment": False}
        config_result.scalar_one_or_none.return_value = config_mock

        session.execute.side_effect = [mock_result, config_result]

        matcher = ProfileMatcher()
        result = await matcher.match(device_info, session)

        assert result.score == 100
        assert result.auto_enroll is False

    async def test_usb_match_case_insensitive(self, device_info: DeviceInfo) -> None:
        """USB VID/PID match is case-insensitive."""
        profile = self._make_profile("ultramic", usb_vid="16D0", usb_pid="0B40")

        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [profile]

        config_result = MagicMock()
        config_mock = MagicMock()
        config_mock.value = {"auto_enrollment": True}
        config_result.scalar_one_or_none.return_value = config_mock
        session.execute.side_effect = [mock_result, config_result]

        matcher = ProfileMatcher()
        result = await matcher.match(device_info, session)

        assert result.score == 100

    async def test_profile_without_match_criteria(self) -> None:
        """Profile with empty config → score 0."""
        profile = MagicMock()
        profile.slug = "bare_profile"
        profile.config = {}

        info = DeviceInfo(alsa_card_index=0, alsa_name="Any", alsa_device="hw:0,0")
        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [profile]
        session.execute.return_value = mock_result

        matcher = ProfileMatcher()
        result = await matcher.match(info, session)
        assert result.score == 0
