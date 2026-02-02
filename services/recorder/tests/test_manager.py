import pytest
from silvasonic.recorder.manager import ProfileManager


@pytest.fixture
def profile_dir(tmp_path):
    """Create a temporary profile directory with a test profile."""
    d = tmp_path / "profiles"
    d.mkdir()
    p = d / "test_mic.yml"
    p.write_text("""
schema_version: "1.0"
slug: "test_mic"
name: "Test Mic"
audio:
  sample_rate: 48000
  channels: 1
  format: "S16LE"
""")
    return d


def test_load_yaml_profile(profile_dir):
    """Test loading a profile from a YAML file."""
    manager = ProfileManager(profile_dir=profile_dir)
    profile = manager.load_profile("test_mic")
    assert profile.name == "Test Mic"
    assert profile.audio.sample_rate == 48000
    # Default values check
    assert profile.processing.chunk_size == 4096
    assert profile.stream.raw_enabled is True


def test_db_override(profile_dir):
    """Test that database configuration overrides file configuration."""
    manager = ProfileManager(profile_dir=profile_dir)
    # DB overrides nested value
    db_config = {"audio": {"sample_rate": 96000}, "processing": {"gain_db": 10.0}}
    profile = manager.load_profile("test_mic", db_config=db_config)
    assert profile.audio.sample_rate == 96000
    assert profile.processing.gain_db == 10.0
    assert profile.name == "Test Mic"  # Unchanged


def test_profile_not_found(profile_dir):
    """Test that loading a non-existent profile raises FileNotFoundError."""
    manager = ProfileManager(profile_dir=profile_dir)
    with pytest.raises(FileNotFoundError):
        manager.load_profile("non_existent")


def test_init_checks_global_profile_dir(mocker, tmp_path):
    """Test that init checks the global PROFILE_DIR."""
    # Mock the global PROFILE_DIR path
    mock_path = mocker.patch("silvasonic.recorder.manager.PROFILE_DIR")
    mock_path.exists.return_value = True

    # Init manager without explicit dir
    from silvasonic.recorder.manager import ProfileManager

    manager = ProfileManager()

    # Should use the mocked global dir
    assert manager.profile_dir == mock_path
    mock_path.exists.assert_called()
