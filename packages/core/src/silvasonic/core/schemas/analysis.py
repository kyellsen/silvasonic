"""Schema of one ``recordings.analysis_state`` entry (ADR-0018, ADR-0033).

``analysis_state`` maps an analyzer to its result for that recording::

    {"birdnet": {"state": "done", "reason": null,
                 "finished_at": "2026-11-10T06:30:00Z", "detection_count": 3}}

While an analyzer works on a recording, its entry is a claim (ADR-0037)::

    {"birdnet": {"state": "running", "claimed_at": "2026-11-10T06:29:58.123456Z"}}

The Worker Pull query treats a recording as handled by an analyzer as soon as
its key is present, whatever the state, except a claim older than
``CLAIM_LEASE``: its worker died, and another takes the recording over.
Reasons are short codes a client can branch on; the error text belongs in the
log, not in the database.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

AnalysisStateValue = Literal["done", "failed", "skipped"]

#: A claim older than this belongs to a worker that died and may be taken over.
CLAIM_LEASE = timedelta(minutes=10)


class AnalysisClaim(BaseModel):
    """An analyzer is working on the recording; replaced by its ``AnalysisState``."""

    state: Literal["running"] = "running"
    claimed_at: datetime

    @classmethod
    def at(cls, moment: datetime) -> AnalysisClaim:
        """A claim made at *moment*."""
        return cls(claimed_at=moment)

    @staticmethod
    def timestamp(moment: datetime) -> str:
        """``claimed_at`` as stored: fixed-width RFC 3339 UTC, so that strings sort by time."""
        return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def to_json(self) -> dict[str, Any]:
        """Serialise for the JSON column."""
        return {"state": self.state, "claimed_at": self.timestamp(self.claimed_at)}

    def to_json_text(self) -> str:
        """The JSON document as text, for SQL's ``json()``."""
        return json.dumps(self.to_json())


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
