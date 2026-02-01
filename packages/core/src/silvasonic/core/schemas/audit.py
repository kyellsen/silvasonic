import time
from typing import Any, Literal

from pydantic import BaseModel, Field


class AuditHeader(BaseModel):
    """Header for audit messages."""

    topic: Literal["audit"] = "audit"
    event: str
    service: str
    instance_id: str
    timestamp: float = Field(default_factory=time.time)


class AuditPayloadContent(BaseModel):
    """Content payload for audit messages."""

    details: dict[str, Any] = Field(default_factory=dict)


class AuditMessage(AuditHeader):
    """Complete audit message."""

    payload: dict[
        str, Any
    ]  # Directly using dict for flexibility as the example schema showed arbitrary keys
