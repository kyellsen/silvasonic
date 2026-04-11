"""Pydantic schemas for structured JSONB payloads and service-boundary contracts.

This package validates:
- ``system_config`` table JSONB blobs (ADR-0023)
- Device / microphone profile configurations
- Cross-service runtime payloads (e.g. Controller → Recorder)
- Detection detail contracts (e.g. BirdNET ``details`` JSONB)
- Cloud storage remote configurations
"""

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
from .recorder import RecorderRuntimeConfig
from .system_config import (
    AuthDefaults,
    BirdnetSettings,
    CloudSyncSettings,
    ProcessorSettings,
    SystemSettings,
)

__all__ = [
    "AudioConfig",
    "AuthDefaults",
    "BaseRcloneConfig",
    "BirdnetSettings",
    "CloudSyncSettings",
    "DriveConfig",
    "MicrophoneProfile",
    "ProcessingConfig",
    "ProcessorSettings",
    "RecorderRuntimeConfig",
    "S3Config",
    "SFTPConfig",
    "StreamConfig",
    "SystemSettings",
    "WebDAVConfig",
    "validate_rclone_config",
]
