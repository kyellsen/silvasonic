"""Pydantic schemas for the ``settings`` table sections (ADR-0023, ADR-0033).

Each schema corresponds to a row (``section``) in the ``settings`` table.
Defaults here MUST mirror ``config/defaults.yml``.

Order: cross-cutting (station, recording, auth) first, then by roadmap
milestone (storage v0.5, sync v0.6, birdnet v0.7).

Keys follow the naming rules of ADR-0033: a quantity carries its unit
(``_s``, ``_percent``, ``_bytes_per_s``), a boolean is an adjective.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

#: Wall-clock time ``HH:MM`` (24 h).
LOCAL_TIME_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


class TimeWindow(BaseModel):
    """A daily window; it may cross midnight (``start`` later than ``end``)."""

    start: str = Field(..., pattern=LOCAL_TIME_PATTERN)
    end: str = Field(..., pattern=LOCAL_TIME_PATTERN)


class StationSettings(BaseModel):
    """Identity of the station (section: ``station``).

    ``id`` is a UUIDv7 the Controller's seeder generates once on first boot
    and never overwrites.
    """

    id: uuid.UUID | None = None
    name: str = "Silvasonic MVP"
    latitude: float | None = None
    longitude: float | None = None


class RecordingSettings(BaseModel):
    """Recording behaviour (section: ``recording``)."""

    auto_enrollment: bool = True
    max_microphones: int = 5


class AuthDefaults(BaseModel):
    """Default admin credentials (section: ``auth``)."""

    default_username: str = "admin"
    default_password: str = "1234"


class StorageSettings(BaseModel):
    """Storage retention and indexing (section: ``storage``, v0.5.0).

    The three ``*_percent`` thresholds are user settings; the remaining keys
    are operational tuning of the Processor that no user sets.
    """

    warning_percent: float = 70.0
    critical_percent: float = 80.0
    emergency_percent: float = 90.0
    cleanup_interval_s: int = 60
    cleanup_batch_files: int = 50
    index_interval_s: float = 2.0


class SyncSettings(BaseModel):
    """Cloud Sync settings (section: ``sync``, v0.6.0).

    Whether the upload runs at all is the ``cloud_sync`` row of the
    ``modules`` table, not a key of this section.

    The ``remote_config`` dict is validated at runtime against the
    type-specific Pydantic schemas in ``silvasonic.core.schemas.cloud_sync``
    (e.g. ``WebDAVConfig``, ``S3Config``) via ``validate_rclone_config()``.

    Remote credentials are **not** seeded via ``defaults.yml``.  They are
    provisioned by the ``CloudSyncSeeder`` from ``SILVASONIC_CLOUD_REMOTE_*``
    environment variables, or configured via Web-UI (v0.9.0).  The module
    stays switched off until a valid remote is configured.

    Sensitive values in ``remote_config`` (user, pass) are Fernet-encrypted
    at rest (``enc:`` prefix).  Decryption uses ``SILVASONIC_ENCRYPTION_KEY``
    from ``.env`` via ``silvasonic.core.crypto.decrypt_value()``.
    """

    poll_interval_s: int = 30
    #: Upload bandwidth limit; ``None`` is unlimited.
    bandwidth_limit_bytes_per_s: int | None = 1_048_576
    #: Upload only within this daily window (UTC); ``None`` is always.
    window: TimeWindow | None = None

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
    """BirdNET inference settings (section: ``birdnet``, v0.7.0).

    Lifecycle toggle (``enabled``) is in ``modules`` (ADR-0029).
    """

    min_confidence: float = 0.65
    clip_padding_s: float = 3.0
    overlap_s: float = 0.0
    sensitivity: float = 1.0
    thread_count: int = 1
    processing_order: Literal["oldest_first", "newest_first"] = "oldest_first"
