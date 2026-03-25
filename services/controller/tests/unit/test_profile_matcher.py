"""Unit tests for ProfileMatcher — profile scoring and auto-enrollment.

All DB dependencies are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.controller.profile_matcher import ProfileMatcher


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

    async def test_no_match_score_0_no_fallback(self, device_info: DeviceInfo) -> None:
        """No matching profile and no generic_usb fallback → score 0, slug None."""
        profile = self._make_profile("other_mic", usb_vid="aaaa", usb_pid="bbbb")

        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [profile]
        session.execute.return_value = mock_result
        # Fallback lookup: generic_usb not in DB
        session.get.return_value = None

        matcher = ProfileMatcher()
        result = await matcher.match(device_info, session)

        assert result.score == 0
        assert result.profile_slug is None
        assert result.auto_enroll is False

    async def test_score_0_fallback_assigns_generic_usb(self, device_info: DeviceInfo) -> None:
        """Score 0 + generic_usb in DB → auto-assign with auto_enroll=True."""
        profile = self._make_profile("other_mic", usb_vid="aaaa", usb_pid="bbbb")

        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [profile]

        # Fallback lookup: generic_usb exists
        generic_profile = MagicMock()
        generic_profile.slug = "generic_usb"
        session.get.return_value = generic_profile

        # auto_enrollment config
        config_result = MagicMock()
        config_mock = MagicMock()
        config_mock.value = {"auto_enrollment": True}
        config_result.scalar_one_or_none.return_value = config_mock
        session.execute.side_effect = [mock_result, config_result]

        matcher = ProfileMatcher()
        result = await matcher.match(device_info, session)

        assert result.score == 0
        assert result.profile_slug == "generic_usb"
        assert result.auto_enroll is True

    async def test_fallback_respects_auto_enrollment_false(self, device_info: DeviceInfo) -> None:
        """Score 0 + generic_usb in DB + auto_enrollment=False → auto_enroll=False."""
        # No matching profiles
        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        # Fallback lookup: generic_usb exists
        generic_profile = MagicMock()
        generic_profile.slug = "generic_usb"
        session.get.return_value = generic_profile

        # auto_enrollment disabled
        config_result = MagicMock()
        config_mock = MagicMock()
        config_mock.value = {"auto_enrollment": False}
        config_result.scalar_one_or_none.return_value = config_mock
        session.execute.side_effect = [mock_result, config_result]

        matcher = ProfileMatcher()
        result = await matcher.match(device_info, session)

        assert result.score == 0
        assert result.profile_slug == "generic_usb"
        assert result.auto_enroll is False

    async def test_no_profiles_in_db(self, device_info: DeviceInfo) -> None:
        """Empty DB (no profiles, no fallback) → no match."""
        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result
        session.get.return_value = None  # No generic_usb fallback

        matcher = ProfileMatcher()
        result = await matcher.match(device_info, session)

        assert result.score == 0
        assert result.profile_slug is None

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
        """Profile with empty config → score 0 (no fallback)."""
        profile = MagicMock()
        profile.slug = "bare_profile"
        profile.config = {}

        info = DeviceInfo(alsa_card_index=0, alsa_name="Any", alsa_device="hw:0,0")
        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [profile]
        session.execute.return_value = mock_result
        session.get.return_value = None  # No generic_usb fallback

        matcher = ProfileMatcher()
        result = await matcher.match(info, session)
        assert result.score == 0
        assert result.profile_slug is None

    async def test_auto_enrollment_default_true_when_no_config(
        self,
        device_info: DeviceInfo,
    ) -> None:
        """auto_enrollment defaults to True when no system config exists in DB."""
        profile = self._make_profile("ultramic_384_evo", usb_vid="16d0", usb_pid="0b40")

        session = AsyncMock(add=MagicMock())
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [profile]

        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None  # No config row

        session.execute.side_effect = [mock_result, config_result]

        matcher = ProfileMatcher()
        result = await matcher.match(device_info, session)

        assert result.score == 100
        assert result.auto_enroll is True
