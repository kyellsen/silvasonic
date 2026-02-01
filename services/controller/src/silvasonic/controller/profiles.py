import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
import yaml
from silvasonic.controller.hardware import AudioDevice

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

    def __init__(self, profiles_dir: str = "/app/profiles") -> None:
        """Initialize ProfileManager."""
        self.profiles_dir = Path(profiles_dir)
        self.profiles: list[RecorderProfile] = []
        self._load_profiles()

    def _load_profiles(self) -> None:
        """Load all YAML profiles from the profiles directory."""
        if not self.profiles_dir.exists():
            logger.warning("profiles_directory_not_found", path=str(self.profiles_dir))
            return

        for p_file in self.profiles_dir.glob("*.yml"):
            try:
                with open(p_file) as f:
                    data = yaml.safe_load(f)

                # Basic validation
                if not data or "slug" not in data:
                    logger.warning("invalid_profile_skipped", file=p_file.name)
                    continue

                # Extract match pattern from audio section
                match_pattern = data.get("audio", {}).get("match_pattern")

                profile = RecorderProfile(
                    slug=data["slug"],
                    name=data.get("name", "Unknown"),
                    match_pattern=match_pattern,
                    raw_config=data,
                )
                self.profiles.append(profile)
                logger.debug("profile_loaded", slug=profile.slug)

            except Exception as e:
                logger.error("failed_to_load_profile", file=p_file.name, error=str(e))

        logger.info("profiles_loaded", count=len(self.profiles))

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
