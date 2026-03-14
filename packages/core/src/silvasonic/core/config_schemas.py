"""Pydantic schemas for system_config JSONB blobs (ADR-0023).

Each schema corresponds to a key in the ``system_config`` table.
Defaults here MUST mirror ``config/defaults.yml``.
"""

from __future__ import annotations

from pydantic import BaseModel


class SystemSettings(BaseModel):
    """System-wide settings (key: ``system``)."""

    latitude: float = 53.55
    longitude: float = 9.99
    max_recorders: int = 5
    max_uploaders: int = 3
    station_name: str = "Silvasonic Dev"
    auto_enrollment: bool = True


class BirdnetSettings(BaseModel):
    """BirdNET inference settings (key: ``birdnet``)."""

    confidence_threshold: float = 0.25


class ProcessorSettings(BaseModel):
    """Processor / Janitor settings (key: ``processor``)."""

    janitor_threshold_warning: float = 70.0
    janitor_threshold_critical: float = 80.0
    janitor_threshold_emergency: float = 90.0
    janitor_interval_seconds: int = 60
    indexer_poll_interval: float = 5.0


class UploaderSettings(BaseModel):
    """Uploader settings (key: ``uploader``)."""

    enabled: bool = True
    poll_interval: int = 30
    bandwidth_limit: str = "1M"
    schedule_start_hour: int | None = 22
    schedule_end_hour: int | None = 6

    # --- Future implementation details (v0.6.0) ---
    # retry_max_attempts: int = 5
    # batch_burst_limit: int = 50


class AuthDefaults(BaseModel):
    """Default admin credentials (key: ``auth``)."""

    default_username: str = "admin"
    default_password: str = "silvasonic"
