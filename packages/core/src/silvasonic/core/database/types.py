"""Column types shared by all station models (ADR-0037)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def to_epoch_us(value: datetime) -> int:
    """Convert a datetime to integer microseconds since the Unix epoch.

    A naive datetime is taken as UTC, as PostgreSQL did with ``TIMESTAMPTZ``
    in a UTC session.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return (value - _EPOCH) // timedelta(microseconds=1)


def from_epoch_us(value: int) -> datetime:
    """Convert integer microseconds since the Unix epoch to an aware UTC datetime."""
    return _EPOCH + timedelta(microseconds=value)


class UTCDateTime(TypeDecorator[datetime]):
    """A point in time, stored as INTEGER microseconds since the epoch (UTC).

    SQLite has no time type.  An integer keeps values exact, sortable and
    compact, and comparisons in SQL work on the stored numbers.  Values come
    back timezone-aware.
    """

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> int | None:
        """Datetime → microseconds."""
        if value is None:
            return None
        if not isinstance(value, datetime):
            msg = f"UTCDateTime expects a datetime, got {type(value).__name__}"
            raise TypeError(msg)
        return to_epoch_us(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        """Microseconds → aware datetime."""
        if value is None:
            return None
        return from_epoch_us(int(value))
