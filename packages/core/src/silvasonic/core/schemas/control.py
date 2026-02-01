import time
from typing import Any, Literal

from pydantic import BaseModel, Field


class ControlHeader(BaseModel):
    """Header for control messages."""

    topic: Literal["control"] = "control"
    command: str
    initiator: str
    target_service: str
    target_instance: str = "*"
    timestamp: float = Field(default_factory=time.time)


class ControlPayloadContent(BaseModel):
    """Content payload for control messages."""

    params: dict[str, Any] = Field(default_factory=dict)


class ControlMessage(ControlHeader):
    """Complete control message."""

    payload: ControlPayloadContent
