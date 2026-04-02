"""Pydantic schemas for configurations outside of system_config."""

from .cloud_sync import (
    BaseRcloneConfig,
    DriveConfig,
    S3Config,
    SFTPConfig,
    WebDAVConfig,
    validate_rclone_config,
)
from .devices import (
    AudioConfig,
    MicrophoneProfile,
    ProcessingConfig,
    StreamConfig,
)

__all__ = [
    "AudioConfig",
    "BaseRcloneConfig",
    "DriveConfig",
    "MicrophoneProfile",
    "ProcessingConfig",
    "S3Config",
    "SFTPConfig",
    "StreamConfig",
    "WebDAVConfig",
    "validate_rclone_config",
]
