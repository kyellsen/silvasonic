"""Schema of one ``recordings.analysis_state`` entry (ADR-0018, ADR-0033).

``analysis_state`` maps an analyzer to its result for that recording::

    {"birdnet": {"state": "done", "reason": null,
                 "finished_at": "2026-11-10T06:30:00Z", "detection_count": 3}}

The Worker Pull query treats a recording as handled by an analyzer as soon as
its key is present, whatever the state. Reasons are short codes a client can
branch on; the error text belongs in the log, not in the database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

AnalysisStateValue = Literal["done", "failed", "skipped"]

#: The audio file could not be found.
REASON_FILE_MISSING = "file_missing"
#: The audio is not at the sample rate the analyzer needs.
REASON_SAMPLE_RATE_UNSUPPORTED = "sample_rate_unsupported"
#: Any other failure; details are in the analyzer's log.
REASON_ERROR = "error"


class AnalysisState(BaseModel):
    """Result of one analyzer for one recording."""

    state: AnalysisStateValue
    reason: str | None = None
    finished_at: datetime
    detection_count: int | None = None

    @classmethod
    def done(cls, detection_count: int) -> AnalysisState:
        """Analysis finished; *detection_count* detections were stored."""
        return cls(state="done", finished_at=datetime.now(UTC), detection_count=detection_count)

    @classmethod
    def failed(cls, reason: str = REASON_ERROR) -> AnalysisState:
        """Analysis was attempted and failed."""
        return cls(state="failed", reason=reason, finished_at=datetime.now(UTC))

    @classmethod
    def skipped(cls, reason: str) -> AnalysisState:
        """Analysis was not attempted, for example because the file is gone."""
        return cls(state="skipped", reason=reason, finished_at=datetime.now(UTC))

    def to_json(self) -> dict[str, Any]:
        """Serialise for JSONB: ``finished_at`` as RFC 3339 UTC (``…Z``)."""
        data = self.model_dump(mode="json")
        data["finished_at"] = self.finished_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return data
