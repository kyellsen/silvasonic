"""Boundary schema for the Recorder service's runtime payload."""

from pydantic import BaseModel, Field
from silvasonic.core.schemas.devices import AudioConfig, ProcessingConfig, StreamConfig


class RecorderRuntimeConfig(BaseModel):
    """Runtime config payload injected by the Controller (ADR-0016).

    The Controller serializes ``profile.config`` (JSONB) which contains
    exactly ``audio``, ``processing``, and ``stream`` sections.  This
    schema validates that payload at the Recorder's service boundary
    and guarantees a strong cross-service data contract.
    """

    audio: AudioConfig = Field(..., description="Hardware capture settings")
    processing: ProcessingConfig = Field(
        default_factory=ProcessingConfig, description="DSP settings"
    )
    stream: StreamConfig = Field(default_factory=StreamConfig, description="Output stream settings")
