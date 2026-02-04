import json
import os
from unittest import mock

import pytest
from silvasonic.recorder.manager import ProfileManager


@pytest.fixture
def manager():
    """Fixture to provide a fresh ProfileManager instance."""
    return ProfileManager()


def test_load_profile_from_env_success(manager):
    """Test loading a profile strictly from environment variable."""
    config = {
        "slug": "test_mic",
        "name": "Test Mic",
        "audio": {"sample_rate": 48000, "channels": 1, "format": "S16LE"},
    }

    with mock.patch.dict(os.environ, {"MIC_CONFIG_JSON": json.dumps(config)}):
        profile = manager.load_profile("test_mic")

        assert profile.slug == "test_mic"
        assert profile.name == "Test Mic"
        assert profile.audio.sample_rate == 48000


def test_load_profile_missing_env(manager):
    """Test that missing environment variable raises ValueError."""
    # Ensure env var is not present
    with mock.patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="Strict Mode: MIC_CONFIG_JSON not set"):
            manager.load_profile("test_mic")


def test_load_profile_invalid_json(manager):
    """Test that invalid JSON raises ValueError."""
    with mock.patch.dict(os.environ, {"MIC_CONFIG_JSON": "{invalid_json"}):
        with pytest.raises(ValueError, match="Invalid JSON"):
            manager.load_profile("test_mic")
