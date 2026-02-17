from datetime import datetime
from typing import Any

from silvasonic.core.database.models.base import Base
from sqlalchemy import Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func


class StorageRemote(Base):  # type: ignore[misc]
    """Configuration for a remote storage provider (e.g. S3, Nextcloud).

    Used by the Uploader service to configure Rclone.
    Credentials in `config` should be encrypted at the application level.
    """

    __tablename__ = "storage_remotes"

    # Slug acts as the primary key/identifier (e.g., 'main-backup')
    slug: Mapped[str] = mapped_column(Text, primary_key=True)

    # Provider type (s3, webdav, sftp, etc.)
    type: Mapped[str] = mapped_column(Text, nullable=False)

    # Human readable name
    name: Mapped[str] = mapped_column(Text, nullable=False)

    # Rclone configuration object (JSON)
    # This stores the fields required for rclone.conf
    # SENSITIVE: Values should be encrypted before storage
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default={})

    # Is this remote currently enabled for sync?
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Optional target path prefix (e.g., /backups/silvasonic)
    target_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Validation hash to verify successful decryption
    encryption_test: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
