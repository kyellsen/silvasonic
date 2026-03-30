"""Boundary schemas for controller-injected Recorder configuration.

This schema represents the controller-injected runtime payload,
not a full persisted microphone profile.  It validates exactly
the three JSONB sections that the Controller serializes from
``MicrophoneProfile.config`` — without metadata fields (slug,
name, etc.) that the Recorder does not need.
"""

from pydantic import BaseModel, Field
from silvasonic.core.schemas.devices import AudioConfig, ProcessingConfig, StreamConfig


class InjectedRecorderConfig(BaseModel):
    """Runtime config payload injected by the Controller (ADR-0016).

    The Controller serializes ``profile.config`` (JSONB) which contains
    exactly ``audio``, ``processing``, and ``stream`` sections.  This
    schema validates that payload at the Recorder's service boundary
    without requiring top-level profile metadata.
    """

    audio: AudioConfig = Field(..., description="Hardware capture settings")
    processing: ProcessingConfig = Field(
        default_factory=ProcessingConfig, description="DSP settings"
    )
    stream: StreamConfig = Field(default_factory=StreamConfig, description="Output stream settings")
