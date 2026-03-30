"""Indexer — Filesystem polling and recording registration.

Scans the Recorder workspace for promoted WAV files in
``{recordings_dir}/*/data/processed/*.wav`` and ``*/data/raw/*.wav``,
extracts metadata via ``soundfile``, and registers new recordings in
the ``recordings`` table.

Idempotent: checks for existing entries by ``file_processed`` (dual-stream)
or ``file_raw`` (raw-only) before insert.
Never touches ``.buffer/`` directories (only promoted, complete segments).

Supports both dual-stream devices (raw + processed) and raw-only devices
where ``processed_enabled=false`` in the microphone profile.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import soundfile as sf  # type: ignore[import-untyped]
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Filename pattern produced by FFmpeg pipeline (v0.6+):
#   Example:  2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav
_FILENAME_TIME_FORMAT = "%Y-%m-%dT%H-%M-%S"
_FILENAME_REGEX = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)_"
    r"(?P<duration>\d+)s_(?P<run_id>[a-f0-9]{8})_(?P<seq>\d{8})\.wav$"
)


@dataclass
class WavMeta:
    """Metadata extracted from a WAV file."""

    duration: float
    sample_rate: int
    filesize: int


@dataclass
class IndexResult:
    """Result of a single indexing run."""

    new: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)


def scan_workspace(recordings_dir: Path) -> list[Path]:
    """Discover all promoted WAV files across all device directories.

    Scans both ``{recordings_dir}/*/data/processed/*.wav`` and
    ``*/data/raw/*.wav``. If both exist for the same device and
    filename, only the processed version is returned (it is the
    primary indexing artifact for dual-stream devices).

    Never returns files from ``.buffer/`` directories.

    Args:
        recordings_dir: Root of the Recorder workspace (e.g. ``/data/recorder``).

    Returns:
        Sorted list of absolute paths to promoted WAV files.
    """
    processed = set(recordings_dir.glob("*/data/processed/*.wav"))
    raw = set(recordings_dir.glob("*/data/raw/*.wav"))

    # Deduplicate: if a processed file exists, skip the raw counterpart.
    # Use (device_dir_name, filename) as the deduplication key.
    processed_keys = {(p.parts[-4], p.name) for p in processed}
    raw_only = {r for r in raw if (r.parts[-4], r.name) not in processed_keys}

    return sorted(processed | raw_only)


def parse_timestamp(filename: str) -> datetime:
    """Parse the recording timestamp from the segment filename.

    Expected format: ``2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav`` (v0.6+)

    Args:
        filename: WAV filename (basename, not full path).

    Returns:
        UTC datetime of segment start.

    Raises:
        ValueError: If filename does not match expected pattern.
    """
    match = _FILENAME_REGEX.match(filename)
    if not match:
        raise ValueError(f"Filename does not match expected pattern: {filename}")

    # For strptime, we strip the mandatory 'Z' suffix
    ts_str = match.group("timestamp")[:-1]

    dt = datetime.strptime(ts_str, _FILENAME_TIME_FORMAT).replace(tzinfo=UTC)

    # Issue warning for Pre-NTP jumps (year < 2020) but allow proceeding for downstreams
    if dt.year < 2020:
        log.warning("indexer.pre_ntp_timestamp", filename=filename, year=dt.year)

    return dt


def extract_metadata(wav_path: Path) -> WavMeta:
    """Extract metadata from a WAV file.

    Args:
        wav_path: Absolute path to the WAV file.

    Returns:
        WavMeta with duration, sample_rate, and filesize.
    """
    info = sf.info(str(wav_path))
    return WavMeta(
        duration=info.duration,
        sample_rate=info.samplerate,
        filesize=os.path.getsize(wav_path),
    )


def resolve_sensor_id(wav_path: Path, recordings_dir: Path) -> str:
    """Extract the sensor/device identifier from the file path.

    Path structure: ``{recordings_dir}/{sensor_id}/data/{raw|processed}/file.wav``

    Args:
        wav_path: Absolute path to the WAV file.
        recordings_dir: Root of the Recorder workspace.

    Returns:
        The sensor_id (workspace directory name).
    """
    rel = wav_path.relative_to(recordings_dir)
    return rel.parts[0]


def _is_raw_path(wav_path: Path) -> bool:
    """Check if a WAV path is from the raw/ stream (not processed/)."""
    return "raw" in wav_path.parts


def resolve_raw_path(processed_path: Path) -> Path:
    """Resolve the corresponding raw WAV path from a processed path.

    Replaces ``/data/processed/`` with ``/data/raw/`` in the path.

    Args:
        processed_path: Path to the processed WAV file.

    Returns:
        Path to the corresponding raw WAV file (may not exist).
    """
    parts = list(processed_path.parts)
    try:
        idx = parts.index("processed")
        parts[idx] = "raw"
    except ValueError:
        pass
    return Path(*parts)


def _relative_path(wav_path: Path, recordings_dir: Path) -> str:
    """Create a relative path string for DB storage.

    Stores paths relative to recordings_dir, e.g.
    ``ultramic-01/data/processed/2026-03-26T01-35-00_10s.wav``.
    """
    return str(wav_path.relative_to(recordings_dir))


async def index_recordings(
    session: AsyncSession,
    recordings_dir: Path,
    *,
    errored_files: set[str] | None = None,
) -> IndexResult:
    """Scan workspace and register new WAV files in the recordings table.

    Idempotent: existing entries (by ``file_processed`` or ``file_raw``
    for raw-only devices) are skipped.

    Uses ``devices.workspace_name`` to resolve the filesystem directory
    name to the device's stable identifier (``devices.name``).

    Args:
        session: Active async DB session.
        recordings_dir: Root of the Recorder workspace.
        errored_files: Optional set of relative paths that previously failed
            metadata extraction.  Skipped immediately without DB interaction.

    Returns:
        IndexResult with counts of new, skipped, and errored files.
    """
    result = IndexResult()
    _errored = errored_files or set()
    wav_files = scan_workspace(recordings_dir)

    for wav_path in wav_files:
        is_raw = _is_raw_path(wav_path)
        rel_path = _relative_path(wav_path, recordings_dir)

        # Skip files that failed extraction in a previous cycle
        if rel_path in _errored:
            result.skipped += 1
            continue

        try:
            # Idempotency check — different column depending on stream type
            if is_raw:
                exists = await session.execute(
                    text("SELECT 1 FROM recordings WHERE file_raw = :fr LIMIT 1"),
                    {"fr": rel_path},
                )
            else:
                exists = await session.execute(
                    text("SELECT 1 FROM recordings WHERE file_processed = :fp LIMIT 1"),
                    {"fp": rel_path},
                )
            if exists.fetchone() is not None:
                result.skipped += 1
                continue

            # Extract metadata
            meta = extract_metadata(wav_path)
            timestamp = parse_timestamp(wav_path.name)
            workspace_dir = resolve_sensor_id(wav_path, recordings_dir)

            # Resolve device: look up by workspace_name (cross-service contract)
            device_row = await session.execute(
                text("SELECT name FROM devices WHERE workspace_name = :ws_name LIMIT 1"),
                {"ws_name": workspace_dir},
            )
            row = device_row.fetchone()
            if row is None:
                result.skipped += 1
                log.info(
                    "indexer.device_not_registered",
                    file=rel_path,
                    sensor_id=workspace_dir,
                )
                continue

            # Use the actual device name (stable_device_id) for the FK
            device_name = row[0]

            # Resolve file paths for both streams
            if is_raw:
                # Raw-only device: no processed file
                rel_raw = rel_path
                rel_processed = None
                filesize_raw = meta.filesize
                filesize_processed = 0
            else:
                # Dual-stream device: processed is primary, derive raw
                rel_processed = rel_path
                raw_path = resolve_raw_path(wav_path)
                rel_raw = _relative_path(raw_path, recordings_dir)
                filesize_raw = os.path.getsize(raw_path) if raw_path.exists() else 0
                filesize_processed = meta.filesize

            # Insert new recording
            await session.execute(
                text("""
                    INSERT INTO recordings (
                        time, sensor_id, file_raw, file_processed,
                        duration, sample_rate, filesize_raw, filesize_processed
                    ) VALUES (
                        :time, :sensor_id, :file_raw, :file_processed,
                        :duration, :sample_rate, :filesize_raw, :filesize_processed
                    )
                """),
                {
                    "time": timestamp,
                    "sensor_id": device_name,
                    "file_raw": rel_raw,
                    "file_processed": rel_processed,
                    "duration": meta.duration,
                    "sample_rate": meta.sample_rate,
                    "filesize_raw": filesize_raw,
                    "filesize_processed": filesize_processed,
                },
            )
            result.new += 1
            log.info(
                "indexer.indexed",
                file=rel_path,
                sensor_id=device_name,
                duration=meta.duration,
            )

        except Exception:
            await session.rollback()
            result.errors += 1
            result.error_details.append(rel_path)
            log.exception("indexer.error", file=rel_path)

    if result.new > 0:
        await session.commit()

    return result
