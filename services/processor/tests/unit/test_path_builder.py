"""Unit tests for the path builder."""

from datetime import UTC, datetime

import pytest
from silvasonic.processor.modules.path_builder import build_remote_path, slugify


@pytest.mark.unit
def test_station_name_slugified() -> None:
    """Test the slugifier handles complex names according to spec."""
    assert slugify("Silvasonic Müller-Station") == "silvasonic-mueller-station"
    assert slugify("  My Awesome Station_01  ") == "my-awesome-station-01"
    assert slugify("Täst_Ø/Sß") == "taest-oesss"


@pytest.mark.unit
def test_builds_correct_remote_path() -> None:
    """Test construction of the target cloud path."""
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    # Base case
    path = build_remote_path("Test Station", "mic_1", dt, "file1.flac")
    assert path == "silvasonic/test-station/mic_1/2024-01-01/file1.flac"

    # Ensures .flac extension
    path2 = build_remote_path("Test Station", "mic_1", dt, "file2.wav")
    assert path2 == "silvasonic/test-station/mic_1/2024-01-01/file2.flac"
