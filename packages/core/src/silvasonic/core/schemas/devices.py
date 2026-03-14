"""Pydantic schemas for hardware devices and profiles."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt


class MatchCriteria(BaseModel):
    """How to match a USB device to this profile (microphone_profiles.md)."""

    usb_vendor_id: str | None = Field(
        default=None, description="USB Vendor ID (stable, from sysfs)"
    )
    usb_product_id: str | None = Field(
        default=None, description="USB Product ID (stable, from sysfs)"
    )
    alsa_name_contains: str | None = Field(
        default=None, description="Case-insensitive ALSA card name substring"
    )


class AudioConfig(BaseModel):
    """Low-level audio capture settings."""

    sample_rate: PositiveInt = Field(
        ..., description="Target sample rate in Hz (e.g., 48000, 384000)"
    )
    channels: PositiveInt = Field(default=1, description="Number of audio channels")
    format: Literal["S16LE", "S24LE", "S32LE"] = Field(
        default="S16LE", description="Audio sample format (bit depth)"
    )
    # Legacy field — kept for backward compatibility
    match_pattern: str | None = Field(
        default=None, description="Regex or substring to match ALSA card name (legacy)"
    )
    # Structured match criteria (replaces match_pattern)
    match: MatchCriteria | None = Field(
        default=None, description="Structured USB/ALSA match criteria for auto-detection"
    )


class ProcessingConfig(BaseModel):
    """Software-side processing settings."""

    gain_db: float = Field(default=0.0, description="Software gain in dB")
    chunk_size: PositiveInt = Field(default=4096, description="Buffer chunk size in frames")
    highpass_filter_hz: float | None = Field(
        default=None, description="Optional High-pass filter cutoff"
    )


class StreamConfig(BaseModel):
    """Stream splitting configuration."""

    raw_enabled: bool = Field(default=True, description="Save Raw stream (native hardware SR)?")
    processed_enabled: bool = Field(default=True, description="Save Processed (48kHz) stream?")
    live_stream_enabled: bool = Field(
        default=False, description="Enable Icecast Opus stream? (v0.9.0)"
    )
    segment_duration_s: PositiveInt = Field(
        default=10, description="File rotation interval in seconds"
    )


class MicrophoneProfile(BaseModel):
    """Configuration profile for a microphone.

    Versioned and structured for extensibility.
    This schema is used to parse the YAML profiles injected into the system.
    """

    model_config = ConfigDict(from_attributes=True)

    # Metadata
    schema_version: str = Field(default="1.0", description="Schema version")
    slug: str = Field(..., description="Unique identifier (e.g. 'ultramic_384_evo')")
    name: str = Field(..., description="Human-readable name")
    description: str | None = Field(default=None, description="User-friendly description")

    # Categories
    manufacturer: str | None = Field(default=None, description="Hardware manufacturer")
    model: str | None = Field(default=None, description="Hardware model name")

    # Config Sections
    audio: AudioConfig = Field(..., description="Hardware capture settings")
    processing: ProcessingConfig = Field(
        default_factory=ProcessingConfig, description="DSP settings"
    )
    stream: StreamConfig = Field(default_factory=StreamConfig, description="Output stream settings")
