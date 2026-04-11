from unittest.mock import AsyncMock, MagicMock

import pytest
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.controller.profile_matcher import GENERIC_USB_SLUG, ProfileMatcher
from silvasonic.core.database.models.profiles import MicrophoneProfile as MicProfileDB
from silvasonic.core.database.models.system import SystemConfig


@pytest.mark.unit
class TestProfileMatcherScoreProfile:
    def test_score_exact_usb_match(self) -> None:
        matcher = ProfileMatcher()
        device_info = DeviceInfo(
            alsa_card_index=1,
            alsa_device="hw:1,0",
            alsa_name="My Mic",
            usb_vendor_id="1234",
            usb_product_id="abcd",
        )
        profile = MicProfileDB(
            slug="my_mic",
            name="My Mic",
            config={"audio": {"match": {"usb_vendor_id": "1234", "usb_product_id": "abcd"}}},
        )
        score = matcher._score_profile(device_info, profile)
        assert score == 100

    def test_score_case_insensitive_usb_match(self) -> None:
        matcher = ProfileMatcher()
        device_info = DeviceInfo(
            alsa_card_index=1,
            alsa_device="hw:1,0",
            alsa_name="My Mic",
            usb_vendor_id="1234",
            usb_product_id="ABCD",
        )
        profile = MicProfileDB(
            slug="my_mic",
            name="My Mic",
            config={"audio": {"match": {"usb_vendor_id": "1234", "usb_product_id": "abcd"}}},
        )
        score = matcher._score_profile(device_info, profile)
        assert score == 100

    def test_score_alsa_substring_match(self) -> None:
        matcher = ProfileMatcher()
        device_info = DeviceInfo(
            alsa_card_index=1,
            alsa_device="hw:1,0",
            alsa_name="USB Advanced Audio Device",
            usb_vendor_id="1234",
            usb_product_id="5678",
        )
        profile = MicProfileDB(
            slug="advanced",
            name="Advanced",
            config={"audio": {"match": {"alsa_name_contains": "Advanced Audio"}}},
        )
        score = matcher._score_profile(device_info, profile)
        assert score == 50

    def test_score_no_match(self) -> None:
        matcher = ProfileMatcher()
        device_info = DeviceInfo(
            alsa_card_index=1,
            alsa_device="hw:1,0",
            alsa_name="Unknown Mic",
            usb_vendor_id="0000",
            usb_product_id="0000",
        )
        profile = MicProfileDB(
            slug="advanced",
            name="Advanced",
            config={
                "audio": {
                    "match": {
                        "usb_vendor_id": "1234",
                        "usb_product_id": "5678",
                        "alsa_name_contains": "Advanced",
                    }
                }
            },
        )
        score = matcher._score_profile(device_info, profile)
        assert score == 0

    def test_score_empty_match_config(self) -> None:
        matcher = ProfileMatcher()
        device_info = DeviceInfo(alsa_card_index=1, alsa_device="hw:1,0", alsa_name="Unknown Mic")
        profile = MicProfileDB(slug="test", name="Test", config={"audio": {"match": {}}})
        score = matcher._score_profile(device_info, profile)
        assert score == 0

    def test_score_no_audio_config(self) -> None:
        matcher = ProfileMatcher()
        device_info = DeviceInfo(alsa_card_index=1, alsa_device="hw:1,0", alsa_name="Unknown Mic")
        profile = MicProfileDB(slug="test", name="Test", config={})
        score = matcher._score_profile(device_info, profile)
        assert score == 0

    def test_score_missing_usb_fields_in_device(self) -> None:
        matcher = ProfileMatcher()
        device_info = DeviceInfo(alsa_card_index=1, alsa_device="hw:1,0", alsa_name="Mic")
        profile = MicProfileDB(
            slug="usb_match",
            config={"audio": {"match": {"usb_vendor_id": "1234", "usb_product_id": "abcd"}}},
        )
        score = matcher._score_profile(device_info, profile)
        assert score == 0


@pytest.mark.asyncio
@pytest.mark.unit
class TestProfileMatcherMatch:
    async def test_match_finds_best_profile(self) -> None:
        matcher = ProfileMatcher()
        device_info = DeviceInfo(
            alsa_card_index=1,
            alsa_device="hw:1,0",
            alsa_name="Test Mic",
            usb_vendor_id="1234",
            usb_product_id="abcd",
        )

        profile_50 = MicProfileDB(
            slug="alsa_match",
            name="ALSA Match",
            config={"audio": {"match": {"alsa_name_contains": "Test"}}},
        )
        profile_100 = MicProfileDB(
            slug="usb_match",
            name="USB Match",
            config={"audio": {"match": {"usb_vendor_id": "1234", "usb_product_id": "abcd"}}},
        )
        profile_0 = MicProfileDB(
            slug="no_match",
            name="No Match",
            config={"audio": {"match": {"usb_vendor_id": "9999"}}},
        )

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = SystemConfig(
            key="system", value={"auto_enrollment": True}
        )
        session.execute.return_value = mock_result

        result = await matcher.match(
            device_info, session, profiles=[profile_50, profile_100, profile_0]
        )

        assert result.profile_slug == "usb_match"
        assert result.score == 100
        assert result.auto_enroll is True

    async def test_match_fallback_generic_usb(self) -> None:
        matcher = ProfileMatcher()
        device_info = DeviceInfo(alsa_card_index=1, alsa_device="hw:1,0", alsa_name="Unknown Mic")

        session = AsyncMock()
        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = SystemConfig(
            key="system", value={"auto_enrollment": False}
        )
        session.execute.return_value = mock_exec_result

        generic_p = MicProfileDB(slug=GENERIC_USB_SLUG, name="Generic")
        session.get.return_value = generic_p

        result = await matcher.match(device_info, session, profiles=[])

        assert result.profile_slug == GENERIC_USB_SLUG
        assert result.score == 0
        assert result.auto_enroll is False

    async def test_match_no_fallback_in_db(self) -> None:
        matcher = ProfileMatcher()
        device_info = DeviceInfo(alsa_card_index=1, alsa_device="hw:1,0", alsa_name="Unknown Mic")

        session = AsyncMock()
        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = SystemConfig(
            key="system", value={"auto_enrollment": False}
        )
        session.execute.return_value = mock_exec_result
        session.get.return_value = None

        result = await matcher.match(device_info, session, profiles=[])

        assert result.profile_slug is None
        assert result.score == 0
        assert result.auto_enroll is False

    async def test_match_loads_profiles_from_db(self) -> None:
        matcher = ProfileMatcher()
        device_info = DeviceInfo(alsa_card_index=1, alsa_device="hw:1,0", alsa_name="Test Mic")

        session = AsyncMock()

        mock_auto_enroll = MagicMock()
        mock_auto_enroll.scalar_one_or_none.return_value = None

        mock_profiles = MagicMock()
        p = MicProfileDB(
            slug="alsa_match", config={"audio": {"match": {"alsa_name_contains": "Test"}}}
        )
        mock_profiles.scalars.return_value.all.return_value = [p]

        session.execute.side_effect = [mock_auto_enroll, mock_profiles]

        result = await matcher.match(device_info, session)

        assert result.profile_slug == "alsa_match"
        assert result.score == 50
        assert session.execute.call_count == 2


@pytest.mark.asyncio
@pytest.mark.unit
class TestProfileMatcherGetAutoEnrollment:
    async def test_get_auto_enrollment_true(self) -> None:
        matcher = ProfileMatcher()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = SystemConfig(
            key="system", value={"auto_enrollment": True}
        )
        session.execute.return_value = mock_result

        assert await matcher._get_auto_enrollment(session) is True

    async def test_get_auto_enrollment_false(self) -> None:
        matcher = ProfileMatcher()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = SystemConfig(
            key="system", value={"auto_enrollment": False}
        )
        session.execute.return_value = mock_result

        assert await matcher._get_auto_enrollment(session) is False

    async def test_get_auto_enrollment_default_if_none(self) -> None:
        matcher = ProfileMatcher()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        assert await matcher._get_auto_enrollment(session) is True

    async def test_get_auto_enrollment_default_if_invalid_value(self) -> None:
        matcher = ProfileMatcher()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = SystemConfig(
            key="system", value="invalid_string"
        )
        session.execute.return_value = mock_result

        assert await matcher._get_auto_enrollment(session) is True
