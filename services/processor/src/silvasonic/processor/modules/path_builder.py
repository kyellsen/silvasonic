"""Path builder for remote cloud storage.

Constructs predictable hierarchical paths:
`silvasonic/{station_name}/{sensor_id}/{YYYY-MM-DD}/{filename}.flac`
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path


def slugify(text: str) -> str:
    """Inline deterministic slugifier without external dependencies.

    Converts to lowercase, removes non-alphanumeric chars,
    and replaces spaces/underscores with hyphens.
    """
    text = text.lower()
    text = re.sub(r"[äæ]", "ae", text)
    text = re.sub(r"[öø]", "oe", text)
    text = re.sub(r"[ü]", "ue", text)
    text = re.sub(r"[ß]", "ss", text)
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def build_remote_path(station_name: str, sensor_id: str, time: datetime, filename: str) -> str:
    """Build the target remote path for a recording.

    Format: ``silvasonic/{station_slug}/{sensor_id}/{YYYY-MM-DD}/{filename}``
    If the filename doesn't end in .flac, it is appended (if needed for target).
    However, the provided filename should already have the correct target extension.

    Args:
        station_name: Raw station name from system config (may contain spaces).
        sensor_id: The ID of the sensor (e.g. `mic_1`).
        time: The start time of the recording.
        filename: The target filename (e.g. `20240101_120000.flac`).

    Returns:
        String path compatible with rclone remotes.
    """
    station_slug = slugify(station_name)
    # Ensure time is UTC for path partitioning
    time = time.replace(tzinfo=UTC) if time.tzinfo is None else time.astimezone(UTC)

    date_str = time.strftime("%Y-%m-%d")

    # Ensure it ends with .flac (standard for cloud sync)
    if not filename.endswith(".flac"):
        filename = f"{Path(filename).stem}.flac"

    return f"silvasonic/{station_slug}/{sensor_id}/{date_str}/{filename}"
