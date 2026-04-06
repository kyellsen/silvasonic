"""Pydantic schemas for Detection JSONB payloads."""

from pydantic import BaseModel


class BirdnetDetectionDetails(BaseModel):
    """Data contract for the ``details`` JSONB field of a BirdNET detection."""

    model_version: str
    sensitivity: float
    overlap: float
    confidence_threshold: float
    location_filter_active: bool
    lat: float | None = None
    lon: float | None = None
    week: int | None = None
