"""Unit tests for silvasonic.core.schemas (devices + cloud sync)."""

import pytest
from pydantic import ValidationError
from silvasonic.core.schemas.cloud_sync import (
    BaseRcloneConfig,
    DriveConfig,
    S3Config,
    SFTPConfig,
    WebDAVConfig,
    validate_rclone_config,
)
from silvasonic.core.schemas.detections import BirdnetDetectionDetails
from silvasonic.core.schemas.devices import (
    AudioConfig,
    MicrophoneProfile,
    ProcessingConfig,
    StreamConfig,
)

# ---------------------------------------------------------------------------
# Device Schemas
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAudioConfig:
    """Tests for AudioConfig schema."""

    def test_valid_config(self) -> None:
        """Constructs with a required sample_rate."""
        cfg = AudioConfig(sample_rate=48000)
        assert cfg.sample_rate == 48000
        assert cfg.channels == 1
        assert cfg.format == "S16LE"
        assert cfg.match_pattern is None

    def test_missing_sample_rate_raises(self) -> None:
        """sample_rate is required — omitting it raises ValidationError."""
        with pytest.raises(ValidationError):
            AudioConfig()  # type: ignore[call-arg]

    def test_custom_format(self) -> None:
        """Accepts valid literal format values."""
        cfg = AudioConfig(sample_rate=384000, format="S24LE")
        assert cfg.format == "S24LE"


@pytest.mark.unit
class TestProcessingConfig:
    """Tests for ProcessingConfig schema."""

    def test_defaults(self) -> None:
        """All fields have sensible defaults."""
        cfg = ProcessingConfig()
        assert cfg.gain_db == 0.0
        assert cfg.chunk_size == 4096
        assert cfg.highpass_filter_hz is None

    def test_override(self) -> None:
        """Custom values are accepted."""
        cfg = ProcessingConfig(gain_db=3.5, chunk_size=2048, highpass_filter_hz=200.0)
        assert cfg.gain_db == 3.5
        assert cfg.highpass_filter_hz == 200.0


@pytest.mark.unit
class TestStreamConfig:
    """Tests for StreamConfig schema."""

    def test_defaults(self) -> None:
        """Default stream configuration values."""
        cfg = StreamConfig()
        assert cfg.raw_enabled is True
        assert cfg.processed_enabled is True
        assert cfg.live_stream_enabled is False
        assert cfg.segment_duration_s == 10


@pytest.mark.unit
class TestMicrophoneProfile:
    """Tests for MicrophoneProfile schema."""

    def test_valid_full_profile(self) -> None:
        """A fully specified profile passes validation."""
        profile = MicrophoneProfile(
            slug="ultramic_384_evo",
            name="Dodotronic Ultramic 384K Evo",
            description="High-end ultrasonic mic",
            manufacturer="Dodotronic",
            model="Ultramic 384K Evo",
            audio=AudioConfig(sample_rate=384000, format="S24LE"),
        )
        assert profile.slug == "ultramic_384_evo"
        assert profile.audio.sample_rate == 384000
        assert profile.processing.gain_db == 0.0  # default
        assert profile.stream.raw_enabled is True  # default

    def test_missing_required_fields_raises(self) -> None:
        """slug, name, and audio are required."""
        with pytest.raises(ValidationError):
            MicrophoneProfile()  # type: ignore[call-arg]

    def test_model_dump(self) -> None:
        """Serialization to dict works correctly."""
        profile = MicrophoneProfile(
            slug="test",
            name="Test Mic",
            audio=AudioConfig(sample_rate=48000),
        )
        d = profile.model_dump()
        assert d["slug"] == "test"
        assert d["audio"]["sample_rate"] == 48000


# ---------------------------------------------------------------------------
# Cloud Sync / Rclone Schemas
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestS3Config:
    """Tests for S3Config schema."""

    def test_valid_config(self) -> None:
        """Builds with required fields."""
        cfg = S3Config(access_key_id="AKIA...", secret_access_key="secret123")
        assert cfg.access_key_id == "AKIA..."
        assert cfg.acl == "private"

    def test_missing_required_raises(self) -> None:
        """Missing access_key_id raises ValidationError."""
        with pytest.raises(ValidationError):
            S3Config()  # type: ignore[call-arg]

    def test_extra_fields_allowed(self) -> None:
        """BaseRcloneConfig allows extra rclone flags."""
        cfg = S3Config(
            access_key_id="key",
            secret_access_key="secret",
            server_side_encryption="AES256",  # extra flag
        )
        assert cfg.model_dump()["server_side_encryption"] == "AES256"


@pytest.mark.unit
class TestWebDAVConfig:
    """Tests for WebDAVConfig schema."""

    def test_valid_config(self) -> None:
        """Builds using 'pass' alias for the password field."""
        cfg = WebDAVConfig.model_validate(
            {"url": "https://nc.example.com/remote.php/dav", "user": "admin", "pass": "secret"}
        )
        assert cfg.url == "https://nc.example.com/remote.php/dav"
        assert cfg.pass_ == "secret"

    def test_missing_required_raises(self) -> None:
        """Missing required fields raises ValidationError."""
        with pytest.raises(ValidationError):
            WebDAVConfig()  # type: ignore[call-arg]


@pytest.mark.unit
class TestSFTPConfig:
    """Tests for SFTPConfig schema."""

    def test_valid_with_key_file(self) -> None:
        """SFTP config with key file instead of password."""
        cfg = SFTPConfig(host="sftp.example.com", user="deploy", key_file="/home/.ssh/id_rsa")
        assert cfg.host == "sftp.example.com"
        assert cfg.pass_ is None
        assert cfg.key_file == "/home/.ssh/id_rsa"


@pytest.mark.unit
class TestDriveConfig:
    """Tests for DriveConfig schema."""

    def test_all_optional(self) -> None:
        """All fields are optional — empty config is valid."""
        cfg = DriveConfig()
        assert cfg.client_id is None
        assert cfg.client_secret is None
        assert cfg.token is None


@pytest.mark.unit
class TestValidateRcloneConfig:
    """Tests for validate_rclone_config function."""

    def test_known_type_s3(self) -> None:
        """Known type 's3' is validated against S3Config schema."""
        result = validate_rclone_config(
            "s3", {"access_key_id": "key", "secret_access_key": "secret"}
        )
        assert isinstance(result, S3Config)

    def test_unknown_type_fallback(self) -> None:
        """Unknown type falls back to BaseRcloneConfig."""
        result = validate_rclone_config("dropbox", {"token": "abc123"})
        assert isinstance(result, BaseRcloneConfig)

    def test_known_type_invalid_data_raises(self) -> None:
        """Invalid data for a known type raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_rclone_config("s3", {"invalid_field": "val"})


# ---------------------------------------------------------------------------
# Worker Contracts
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBirdnetDetectionDetails:
    """Tests for BirdnetDetectionDetails schema."""

    def test_valid_detection(self) -> None:
        """A fully complete detection payload parses properly."""
        payload = {
            "model_version": "v2.4",
            "sensitivity": 1.0,
            "overlap": 0.0,
            "confidence_threshold": 0.5,
            "location_filter_active": True,
            "lat": 51.5,
            "lon": 10.5,
            "week": 22,
        }
        det = BirdnetDetectionDetails.model_validate(payload)
        assert det.model_version == "v2.4"
        assert det.lat == 51.5
        assert det.lon == 10.5
        assert det.week == 22

    def test_missing_required_fields_raises(self) -> None:
        """Missing required fields raises ValidationError."""
        with pytest.raises(ValidationError):
            BirdnetDetectionDetails.model_validate({"model_version": "v2.4"})

    def test_optional_defaults(self) -> None:
        """Optional fields gracefully default to None."""
        payload = {
            "model_version": "v2.4",
            "sensitivity": 1.0,
            "overlap": 0.0,
            "confidence_threshold": 0.5,
            "location_filter_active": False,
        }
        det = BirdnetDetectionDetails.model_validate(payload)
        assert det.lat is None
        assert det.lon is None
        assert det.week is None
