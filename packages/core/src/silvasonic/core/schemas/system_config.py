"""Pydantic schemas for system_config JSONB blobs (ADR-0023).

Each schema corresponds to a key in the ``system_config`` table.
Defaults here MUST mirror ``config/defaults.yml``.

Order: cross-cutting (system, auth) first, then by roadmap milestone
(processor v0.5, cloud sync v0.6, birdnet v0.7).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class SystemSettings(BaseModel):
    """System-wide settings (key: ``system``)."""

    latitude: float | None = None
    longitude: float | None = None
    max_recorders: int = 5
    station_name: str = "Silvasonic MVP"
    auto_enrollment: bool = True


class AuthDefaults(BaseModel):
    """Default admin credentials (key: ``auth``)."""

    default_username: str = "admin"
    default_password: str = "1234"


class ProcessorSettings(BaseModel):
    """Processor / Janitor settings (key: ``processor``, v0.5.0)."""

    janitor_threshold_warning: float = 70.0
    janitor_threshold_critical: float = 80.0
    janitor_threshold_emergency: float = 90.0
    janitor_interval_seconds: int = 60
    janitor_batch_size: int = 50
    indexer_poll_interval: float = 2.0


class CloudSyncSettings(BaseModel):
    """Cloud Sync settings (key: ``cloud_sync``, v0.6.0).

    The ``remote_config`` dict is validated at runtime against the
    type-specific Pydantic schemas in ``silvasonic.core.schemas.cloud_sync``
    (e.g. ``WebDAVConfig``, ``S3Config``) via ``validate_rclone_config()``.

    Remote credentials are **not** seeded via ``defaults.yml``.  They are
    provisioned by the ``CloudSyncSeeder`` from ``SILVASONIC_CLOUD_REMOTE_*``
    environment variables, or configured via Web-UI (v0.9.0).  The worker
    stays inactive (``enabled=false``) until a valid remote is configured.

    Sensitive values in ``remote_config`` (user, pass) are Fernet-encrypted
    at rest (``enc:`` prefix).  Decryption uses ``SILVASONIC_ENCRYPTION_KEY``
    from ``.env`` via ``silvasonic.core.crypto.decrypt_value()``.
    """

    enabled: bool = False
    poll_interval: int = 30
    bandwidth_limit: str = "1M"
    schedule_start_hour: int | None = None
    schedule_end_hour: int | None = None

    # --- Remote target (single-target KISS, v0.6.0) ---
    remote_type: str | None = None
    """Rclone backend type: ``"webdav"``, ``"s3"``, ``"sftp"``, ``"drive"``."""

    remote_name: str = "silvasonic-remote"
    """Rclone remote name used in the generated ``rclone.conf``."""

    remote_config: dict[str, Any] = {}
    """Type-specific config passed to the rclone backend (url, user, pass, etc.)."""

    # --- Future implementation details (post-v1.0.0) ---
    # batch_burst_limit: int = 50


class BirdnetSettings(BaseModel):
    """BirdNET inference settings (key: ``birdnet``, v0.7.0).

    Lifecycle toggle (``enabled``) is in ``managed_services`` (ADR-0029).
    """

    confidence_threshold: float = 0.65
    clip_padding_seconds: float = 3.0
    overlap: float = 0.0
    sensitivity: float = 1.0
    threads: int = 1
    processing_order: Literal["oldest_first", "newest_first"] = "oldest_first"
