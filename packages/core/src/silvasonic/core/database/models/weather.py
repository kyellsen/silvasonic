from datetime import datetime
from typing import Any

from silvasonic.core.database.models.base import Base
from silvasonic.core.database.types import UTCDateTime
from sqlalchemy import JSON, Boolean, Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column


class WeatherObservation(Base):
    """Hybrid environmental data from local sensors (BME280) and external APIs."""

    __tablename__ = "weather_observations"

    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), primary_key=True)

    # Source identifier (e.g. 'local_bme280', 'openmeteo')
    # One row per observation time and source
    source: Mapped[str] = mapped_column(Text, primary_key=True)

    station_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    temperature_c: Mapped[float] = mapped_column(Float, nullable=True)
    humidity_percent: Mapped[float] = mapped_column(Float, nullable=True)
    pressure_hpa: Mapped[float] = mapped_column(Float, nullable=True)

    wind_speed_kmh: Mapped[float] = mapped_column(Float, nullable=True)
    wind_gusts_kmh: Mapped[float] = mapped_column(Float, nullable=True)
    precipitation_mm: Mapped[float] = mapped_column(Float, nullable=True)

    cloud_cover_percent: Mapped[int] = mapped_column(Integer, nullable=True)
    uv_index: Mapped[float] = mapped_column(Float, nullable=True)

    sunshine_duration_s: Mapped[float] = mapped_column(Float, nullable=True)
    weather_code: Mapped[int] = mapped_column(Integer, nullable=True)

    forecast: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Overflow Buffer for extra sensors
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
