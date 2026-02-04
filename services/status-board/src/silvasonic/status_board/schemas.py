from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DeviceBase(BaseModel):
    """Base Device fields."""

    name: str = Field(description="Logical name of the device")
    enrollment_status: str = Field(description="pending, enrolled, or ignored")
    profile_slug: str | None = Field(default=None, description="Linked microphone profile")


class DeviceUpdate(BaseModel):
    """Payload for updating a device state."""

    enrollment_status: str | None = Field(default=None, pattern="^(pending|enrolled|ignored)$")
    profile_slug: str | None = None
    logical_name: str | None = None
    enabled: bool | None = None


class DeviceResponse(DeviceBase):
    """Full Device response."""

    serial_number: str
    model: str
    status: str
    last_seen: Any | None
    enabled: bool
    config: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class ProfileCreate(BaseModel):
    """Payload for creating a new profile."""

    slug: str = Field(pattern="^[a-z0-9-_]+$")
    name: str
    match_pattern: str | None = None
    config: dict[str, Any]


class ProfileResponse(ProfileCreate):
    """Full Profile response."""

    description: str | None = None
    is_system: bool

    model_config = ConfigDict(from_attributes=True)
