import json

import pytest
from silvasonic.recorder.manager import ProfileManager


@pytest.fixture
def manager():
    """Fixture to provide a fresh ProfileManager instance."""
    return ProfileManager()


def test_load_profile_from_env_success(manager, monkeypatch):
    """Test loading a profile strictly from environment variable."""
    config = {
        "slug": "test_mic",
        "name": "Test Mic",
        "audio": {"sample_rate": 48000, "channels": 1, "format": "S16LE"},
    }

    from silvasonic.recorder.settings import settings

    monkeypatch.setattr(settings, "MIC_CONFIG_JSON", json.dumps(config))

    profile = manager.load_profile("test_mic")

    assert profile.slug == "test_mic"
    assert profile.name == "Test Mic"
    assert profile.audio.sample_rate == 48000


def test_load_profile_missing_env(manager, monkeypatch):
    """Test that missing environment variable raises ValueError."""
    from silvasonic.recorder.settings import settings

    # Ensure it's None
    monkeypatch.setattr(settings, "MIC_CONFIG_JSON", None)

    with pytest.raises(ValueError, match="Strict Mode: MIC_CONFIG_JSON not set"):
        manager.load_profile("test_mic")


def test_load_profile_invalid_json(manager, monkeypatch):
    """Test that invalid JSON raises ValueError."""
    from silvasonic.recorder.settings import settings

    monkeypatch.setattr(settings, "MIC_CONFIG_JSON", "{invalid_json")

    with pytest.raises(ValueError, match="Invalid JSON"):
        manager.load_profile("test_mic")
