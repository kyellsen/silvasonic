"""Pydantic schemas for structured JSONB payloads and service-boundary contracts.

This package validates:
- ``settings`` table sections (ADR-0023)
- Microphone profile configurations
- ``recordings.analysis_state`` entries
- Cross-service runtime payloads (e.g. Controller → Recorder)
- Detection detail contracts (e.g. BirdNET ``details`` JSONB)
- Cloud storage remote configurations
"""

from .analysis import AnalysisState
from .cloud_sync import (
    BaseRcloneConfig,
    DriveConfig,
    S3Config,
    SFTPConfig,
    WebDAVConfig,
    validate_rclone_config,
)
from .microphones import (
    AudioConfig,
    MicrophoneProfile,
    ProcessingConfig,
    StreamConfig,
)
from .recorder import RecorderRuntimeConfig
from .settings import (
    AuthDefaults,
    BirdnetSettings,
    RecordingSettings,
    StationSettings,
    StorageSettings,
    SyncSettings,
    TimeWindow,
)

__all__ = [
    "AnalysisState",
    "AudioConfig",
    "AuthDefaults",
    "BaseRcloneConfig",
    "BirdnetSettings",
    "DriveConfig",
    "MicrophoneProfile",
    "ProcessingConfig",
    "RecorderRuntimeConfig",
    "RecordingSettings",
    "S3Config",
    "SFTPConfig",
    "StationSettings",
    "StorageSettings",
    "StreamConfig",
    "SyncSettings",
    "TimeWindow",
    "WebDAVConfig",
    "validate_rclone_config",
]
