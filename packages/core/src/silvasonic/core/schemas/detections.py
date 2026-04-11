"""Pydantic schemas for Detection JSONB payloads."""

from pydantic import BaseModel, Field


class BirdnetDetectionDetails(BaseModel):
    """Data contract for the ``details`` JSONB field of a BirdNET detection."""

    model_version: str = Field(
        ...,
        pattern=r"(?s).*\d.*\d.*",
        description="Dynamic model version from file name (min 2 digits).",
    )
    sensitivity: float
    overlap: float
    confidence_threshold: float
    location_filter_active: bool
    lat: float | None = None
    lon: float | None = None
    week: int | None = None
