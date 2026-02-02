import re
from dataclasses import dataclass
from typing import Any

import structlog
from silvasonic.controller.hardware import AudioDevice
from silvasonic.core.database.models.profiles import MicrophoneProfile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


@dataclass
class RecorderProfile:
    """Represents a loaded recorder profile."""

    slug: str
    name: str
    match_pattern: str | None
    raw_config: dict[str, Any]


class ProfileManager:
    """Manages loading and matching of hardware profiles."""

    def __init__(self) -> None:
        """Initialize ProfileManager."""
        self.profiles: list[RecorderProfile] = []

    async def load_profiles(self, session: AsyncSession) -> None:
        """Load all profiles from the database."""
        try:
            stmt = select(MicrophoneProfile)
            result = await session.execute(stmt)
            db_profiles = result.scalars().all()

            self.profiles = []
            for db_p in db_profiles:
                profile = RecorderProfile(
                    slug=db_p.slug,
                    name=db_p.name,
                    match_pattern=db_p.match_pattern,
                    raw_config=db_p.config,
                )
                self.profiles.append(profile)
                logger.debug("profile_loaded_from_db", slug=profile.slug)

            logger.info("profiles_loaded", count=len(self.profiles))

        except Exception as e:
            logger.error("failed_to_load_profiles_from_db", error=str(e))

    def find_profile_for_device(self, device: AudioDevice) -> str | None:
        """Find a matching profile slug for the given hardware device."""
        # Combine ID and Description for matching
        search_text = f"{device.id} {device.description}"

        for profile in self.profiles:
            if not profile.match_pattern:
                continue

            try:
                if re.search(profile.match_pattern, search_text, re.IGNORECASE):
                    logger.info(
                        "profile_matched",
                        device=device.serial_number,
                        profile=profile.slug,
                        pattern=profile.match_pattern,
                    )
                    return profile.slug
            except re.error:
                logger.warning(
                    "invalid_regex_pattern",
                    profile=profile.slug,
                    pattern=profile.match_pattern,
                )

        return None
