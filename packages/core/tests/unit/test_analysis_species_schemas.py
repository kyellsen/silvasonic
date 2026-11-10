"""Unit tests for AnalysisState, species slugs and the settings defaults (ADR-0033)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel, ValidationError
from silvasonic.core.schemas.analysis import (
    REASON_ERROR,
    REASON_FILE_MISSING,
    REASON_SAMPLE_RATE_UNSUPPORTED,
    AnalysisState,
)
from silvasonic.core.schemas.settings import (
    AuthDefaults,
    BirdnetSettings,
    RecordingSettings,
    StationSettings,
    StorageSettings,
    SyncSettings,
)
from silvasonic.core.schemas.species import species_id

_DEFAULTS_YML = Path(__file__).resolve().parents[4] / "config" / "defaults.yml"


@pytest.mark.unit
class TestAnalysisState:
    """One ``recordings.analysis_state`` entry."""

    def test_done(self) -> None:
        """Done carries the detection count and no reason."""
        s = AnalysisState.done(3)
        assert s.state == "done"
        assert s.reason is None
        assert s.detection_count == 3
        assert s.finished_at.tzinfo is not None

    def test_failed_defaults_to_error(self) -> None:
        """A failure without a specific code is ``error``."""
        s = AnalysisState.failed()
        assert s.state == "failed"
        assert s.reason == REASON_ERROR
        assert s.detection_count is None

    def test_failed_with_reason(self) -> None:
        """A failure keeps its reason code."""
        assert AnalysisState.failed(REASON_FILE_MISSING).reason == "file_missing"

    def test_skipped(self) -> None:
        """Skipped carries its reason code."""
        s = AnalysisState.skipped(REASON_SAMPLE_RATE_UNSUPPORTED)
        assert s.state == "skipped"
        assert s.reason == "sample_rate_unsupported"

    def test_unknown_state_rejected(self) -> None:
        """Only done, failed and skipped are stored."""
        with pytest.raises(ValidationError):
            AnalysisState.model_validate({"state": "crashed", "finished_at": datetime.now(UTC)})

    def test_to_json_rfc3339_utc(self) -> None:
        """to_json gives plain JSON with a ``Z``-suffixed UTC timestamp."""
        s = AnalysisState(
            state="done",
            finished_at=datetime(2026, 11, 10, 6, 30, tzinfo=UTC),
            detection_count=0,
        )
        assert s.to_json() == {
            "state": "done",
            "reason": None,
            "finished_at": "2026-11-10T06:30:00Z",
            "detection_count": 0,
        }

    def test_to_json_roundtrip(self) -> None:
        """A stored entry parses back to the same state."""
        s = AnalysisState.failed(REASON_FILE_MISSING)
        back = AnalysisState.model_validate(s.to_json())
        assert back == s
        assert s.to_json()["finished_at"].endswith("Z")


@pytest.mark.unit
class TestSpeciesId:
    """species_id slugs a scientific name."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Turdus merula", "turdus-merula"),
            ("Parus  major", "parus-major"),
            ("Corvus corone/cornix", "corvus-corone-cornix"),
            ("  (Human vocal)  ", "human-vocal"),
            ("Engine", "engine"),
            ("Dog", "dog"),
            ("Strix aluco 2", "strix-aluco-2"),
        ],
    )
    def test_slug(self, name: str, expected: str) -> None:
        """Lowercase; runs of non-alphanumerics become one dash; no edge dashes."""
        assert species_id(name) == expected


@pytest.mark.unit
class TestSettingsDefaultsMatchYaml:
    """Schema defaults MUST mirror config/defaults.yml (settings.py docstring)."""

    SCHEMAS: dict[str, type[BaseModel]] = {  # noqa: RUF012
        "station": StationSettings,
        "recording": RecordingSettings,
        "auth": AuthDefaults,
        "storage": StorageSettings,
        "sync": SyncSettings,
        "birdnet": BirdnetSettings,
    }

    @pytest.fixture(scope="class")
    def defaults(self) -> dict[str, Any]:
        """The factory defaults file."""
        data = yaml.safe_load(_DEFAULTS_YML.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        return data

    def test_sections(self, defaults: dict[str, Any]) -> None:
        """Every YAML section has a schema and vice versa."""
        assert set(defaults) == set(self.SCHEMAS)

    @pytest.mark.parametrize("section", list(SCHEMAS))
    def test_values(self, defaults: dict[str, Any], section: str) -> None:
        """YAML values equal the schema defaults; station.id is left to the seeder."""
        schema_defaults = self.SCHEMAS[section]().model_dump(mode="json")
        if section == "station":
            assert "id" not in defaults[section]
            assert schema_defaults.pop("id") is None
        assert defaults[section] == schema_defaults
