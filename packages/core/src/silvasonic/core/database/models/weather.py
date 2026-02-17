from datetime import datetime
from typing import Any

from silvasonic.core.database.models.base import Base
from sqlalchemy import Boolean, DateTime, Float, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Weather(Base):
    """Hybrid environmental data from local sensors (BME280) and external APIs.

    Designed to be a TimescaleDB hypertable partitioned by `time`.
    """

    __tablename__ = "weather"

    # TimescaleDB Partition Key
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    # Source identifier (e.g. 'local_bme280', 'openmeteo')
    # Part of composite PK in standard SQL, but for Timescale, time is main partition
    source: Mapped[str] = mapped_column(Text, primary_key=True)

    station_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    temp_c: Mapped[float] = mapped_column(Float, nullable=True)
    humidity: Mapped[float] = mapped_column(Float, nullable=True)
    pressure_hpa: Mapped[float] = mapped_column(Float, nullable=True)

    wind_speed_kmh: Mapped[float] = mapped_column(Float, nullable=True)
    wind_gusts_kmh: Mapped[float] = mapped_column(Float, nullable=True)
    precipitation_mm: Mapped[float] = mapped_column(Float, nullable=True)

    cloud_cover: Mapped[int] = mapped_column(Integer, nullable=True)
    uv_index: Mapped[float] = mapped_column(Float, nullable=True)

    sunshine_duration: Mapped[float] = mapped_column(Float, nullable=True)
    weather_code: Mapped[int] = mapped_column(Integer, nullable=True)

    is_forecast: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Overflow Buffer for extra sensors
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, default={})
