"""Pydantic schemas for Uploader and Rclone remote configurations."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BaseRcloneConfig(BaseModel):
    """Base configuration for Rclone remotes."""

    model_config = ConfigDict(extra="allow")  # Allow extra rclone flags


class S3Config(BaseRcloneConfig):
    """Configuration for S3-compatible storage."""

    access_key_id: str = Field(..., description="AWS Access Key ID")
    secret_access_key: str = Field(..., description="AWS Secret Access Key")
    endpoint: str | None = Field(None, description="Custom S3 Endpoint")
    region: str | None = Field(None, description="AWS Region")
    acl: str = "private"


class WebDAVConfig(BaseRcloneConfig):
    """Configuration for WebDAV storage."""

    url: str = Field(..., description="WebDAV URL")
    vendor: str | None = Field(None, description="Vendor (e.g. nextcloud)")
    user: str = Field(..., description="Username")
    pass_: str = Field(..., alias="pass", description="Password")  # 'pass' is reserved in Python


class SFTPConfig(BaseRcloneConfig):
    """Configuration for SFTP storage."""

    host: str = Field(..., description="SFTP Host")
    user: str = Field(..., description="Username")
    pass_: str | None = Field(None, alias="pass", description="Password")
    key_file: str | None = Field(None, description="Path to private key file")


class DriveConfig(BaseRcloneConfig):
    """Configuration for Google Drive storage."""

    client_id: str | None = None
    client_secret: str | None = None
    token: str | None = Field(None, description="OAuth Token JSON")


# Registry for validation
CONFIG_SCHEMAS: dict[str, type[BaseRcloneConfig]] = {
    "s3": S3Config,
    "webdav": WebDAVConfig,
    "sftp": SFTPConfig,
    "drive": DriveConfig,
}


def validate_rclone_config(type_slug: str, config: dict[str, Any]) -> BaseRcloneConfig:
    """Validate a raw config dictionary against the schema for the given type."""
    schema = CONFIG_SCHEMAS.get(type_slug)
    if not schema:
        # Fallback for unknown types (e.g. dropbox, box)
        # We perform basic validation that it's a dict, but allow it.
        return BaseRcloneConfig(**config)

    return schema.model_validate(config)
