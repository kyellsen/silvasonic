import json
from typing import Any

import structlog
from silvasonic.core.schemas.devices import MicrophoneProfile
from silvasonic.recorder.settings import settings

logger = structlog.get_logger()


class ProfileManager:
    """Manages loading of Microphone Profiles via Environment Injection."""

    def load_profile(
        self, profile_name: str, db_config: dict[str, Any] | None = None
    ) -> MicrophoneProfile:
        """Load a profile strictly from the MIC_CONFIG_JSON environment variable.

        Args:
            profile_name: Name of the profile (for logging).
            db_config: Ignored in strict injection mode, as config comes fully formed.

        Returns:
            Validated MicrophoneProfile object.

        Raises:
            ValueError: If MIC_CONFIG_JSON is missing.
        """
        raw_config = settings.MIC_CONFIG_JSON

        if raw_config:
            logger.info("loading_profile_from_env", profile=profile_name)
            try:
                config_data = json.loads(raw_config)

                # Robustness: Inject metadata if missing (e.g. from Controller overrides)
                if "slug" not in config_data:
                    config_data["slug"] = profile_name
                if "name" not in config_data:
                    config_data["name"] = profile_name

                return MicrophoneProfile(**config_data)
            except json.JSONDecodeError as e:
                logger.error("invalid_mic_config_json", error=str(e))
                raise ValueError(f"Invalid JSON in MIC_CONFIG_JSON: {e}") from e

        # Strict Mode: No Fallback
        error_msg = f"Strict Mode: MIC_CONFIG_JSON not set for profile '{profile_name}'"
        logger.critical("missing_mic_config_env", profile=profile_name)
        raise ValueError(error_msg)
