from pathlib import Path
from typing import Any

import structlog
import yaml
from silvasonic.core.schemas.devices import MicrophoneProfile

logger = structlog.get_logger()

# In-container path (mounted)
PROFILE_DIR = Path("/etc/silvasonic/profiles")
# Fallback for local development
DEV_PROFILE_DIR = Path(__file__).parents[4] / "config/profiles"


class ProfileManager:
    """Manages loading and merging of Microphone Profiles."""

    def __init__(self, profile_dir: Path | None = None) -> None:
        """Initialize the manager with a specific profile directory."""
        # Debugging path detection
        logger.info("checking_profile_dir", path=str(PROFILE_DIR), exists=PROFILE_DIR.exists())
        if PROFILE_DIR.exists():
            logger.info("profile_dir_contents", contents=[p.name for p in PROFILE_DIR.iterdir()])

        self.profile_dir = profile_dir or (PROFILE_DIR if PROFILE_DIR.exists() else DEV_PROFILE_DIR)
        logger.info("selected_profile_dir", path=str(self.profile_dir))

    def _recursive_update(self, base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """Recursively update a dictionary."""
        for key, value in overrides.items():
            if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                self._recursive_update(base[key], value)
            else:
                base[key] = value
        return base

    def load_profile(
        self, profile_name: str, db_config: dict[str, Any] | None = None
    ) -> MicrophoneProfile:
        """Load a profile by name from YAML and optionally merge with DB config.

        Args:
            profile_name: The base filename (without .yml) of the system profile.
            db_config: Optional dictionary from the database 'devices.config' column.

        Returns:
            Validated MicrophoneProfile object.
        """
        logger.info("loading_profile", profile=profile_name)

        # 1. Load YAML System Profile
        yaml_path = self.profile_dir / f"{profile_name}.yml"
        if not yaml_path.exists():
            raise FileNotFoundError(f"Profile {profile_name} not found at {yaml_path}")

        with open(yaml_path) as f:
            base_config = yaml.safe_load(f)

        # 2. Merge DB Config (User Overrides)
        if db_config:
            logger.info("applying_user_overrides", overrides=db_config.keys())
            base_config = self._recursive_update(base_config, db_config)

        # 3. Validate via Pydantic
        return MicrophoneProfile(**base_config)
