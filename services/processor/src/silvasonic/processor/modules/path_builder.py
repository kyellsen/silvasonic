"""Path builder for remote cloud storage.

Constructs predictable hierarchical paths:
`silvasonic/{station_name}/{profile_slug}-{hardware_id}/{YYYY-MM-DD}/{filename}.flac`
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


def build_remote_path(
    station_name: str, profile_slug: str, hardware_id: str, started_at: datetime, filename: str
) -> str:
    """Build the target remote path for a recording.

    Format: ``silvasonic/{station_slug}/{profile_slug}-{hardware_id}/{YYYY-MM-DD}/{filename}``
    If the filename doesn't end in .flac, it is appended (if needed for target).
    However, the provided filename should already have the correct target extension.

    Args:
        station_name: Raw station name from the ``station`` settings (may contain spaces).
        profile_slug: Microphone profile slug (e.g. `ultramic_384_evo`).
        hardware_id: The microphone's ``hardware_id`` (Stable Device ID, e.g. `mic_1`).
        started_at: The start time of the recording.
        filename: The target filename (e.g. `20240101_120000.flac`).

    Returns:
        String path compatible with rclone remotes.
    """
    station_slug = slugify(station_name)
    prof_slug = slugify(profile_slug)
    # Ensure time is UTC for path partitioning
    started_at = (
        started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at.astimezone(UTC)
    )

    date_str = started_at.strftime("%Y-%m-%d")

    # Ensure it ends with .flac (standard for cloud sync)
    if not filename.endswith(".flac"):
        filename = f"{Path(filename).stem}.flac"

    return f"silvasonic/{station_slug}/{prof_slug}-{hardware_id}/{date_str}/{filename}"
