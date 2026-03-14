"""Profile matcher — auto-assigns microphone profiles to detected devices.

Implements a 3-level scoring system (ADR-0016):
- **Score 100:** Exact USB Vendor+Product ID match → auto-enroll
- **Score 50:** ALSA card name substring match → suggest profile
- **Score 0:** No match → device stays pending
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.core.database.models.profiles import MicrophoneProfile as MicProfileDB
from silvasonic.core.database.models.system import SystemConfig
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


class MatchResult(BaseModel):
    """Result of a profile matching attempt."""

    profile_slug: str | None = Field(default=None, description="Matched profile slug")
    score: int = Field(default=0, description="Match score (0, 50, 100)")
    auto_enroll: bool = Field(default=False, description="Should auto-enroll this device?")


class ProfileMatcher:
    """Match detected devices to microphone profiles.

    Uses the ``match`` field of :class:`MicrophoneProfile` to score
    candidates against a :class:`DeviceInfo`.
    """

    async def match(
        self,
        device_info: DeviceInfo,
        session: AsyncSession,
    ) -> MatchResult:
        """Find the best matching profile for a device.

        Args:
            device_info: Detected device information.
            session: Active async DB session.

        Returns:
            :class:`MatchResult` with best match (or no match).
        """
        # Load all profiles
        result = await session.execute(select(MicProfileDB))
        profiles = result.scalars().all()

        best: MatchResult = MatchResult()

        for profile in profiles:
            score = self._score_profile(device_info, profile)
            if score > best.score:
                best = MatchResult(profile_slug=profile.slug, score=score)

        # Check auto_enrollment flag if we have a match
        if best.score >= 100:
            auto_enrollment = await self._get_auto_enrollment(session)
            best.auto_enroll = auto_enrollment

        if best.profile_slug:
            log.debug(
                "profile_matcher.matched",
                device_id=device_info.stable_device_id,
                profile=best.profile_slug,
                score=best.score,
                auto_enroll=best.auto_enroll,
            )
        else:
            log.debug(
                "profile_matcher.no_match",
                device_id=device_info.stable_device_id,
            )

        return best

    def _score_profile(self, device_info: DeviceInfo, profile: MicProfileDB) -> int:
        """Score a single profile against a device.

        Returns:
            100 for exact USB match, 50 for ALSA name match, 0 otherwise.
        """
        config = profile.config or {}

        # Check for structured match criteria in config
        match_criteria = config.get("audio", {}).get("match", {})
        if not match_criteria:
            return 0

        # Score 100: Exact USB Vendor+Product ID match
        usb_vid = match_criteria.get("usb_vendor_id")
        usb_pid = match_criteria.get("usb_product_id")
        if (
            usb_vid
            and usb_pid
            and device_info.usb_vendor_id
            and device_info.usb_product_id
            and usb_vid.lower() == device_info.usb_vendor_id.lower()
            and usb_pid.lower() == device_info.usb_product_id.lower()
        ):
            return 100

        # Score 50: ALSA card name substring match
        alsa_contains = match_criteria.get("alsa_name_contains")
        if alsa_contains and alsa_contains.lower() in device_info.alsa_name.lower():
            return 50

        return 0

    async def _get_auto_enrollment(self, session: AsyncSession) -> bool:
        """Read the ``auto_enrollment`` flag from ``system_config``.

        Defaults to ``True`` if not set (per user decision).
        """
        result = await session.execute(select(SystemConfig).where(SystemConfig.key == "system"))
        config = result.scalar_one_or_none()
        if config and isinstance(config.value, dict):
            return bool(config.value.get("auto_enrollment", True))
        return True
