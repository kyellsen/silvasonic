"""Indexer — Filesystem polling and recording registration.

Scans the Recorder workspace for promoted WAV files in
``{recordings_dir}/*/data/processed/*.wav``, extracts metadata via
``soundfile``, and registers new recordings in the ``recordings`` table.

Idempotent: checks for existing entries by ``file_processed`` before insert.
Never touches ``.buffer/`` directories (only promoted, complete segments).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import soundfile as sf  # type: ignore[import-untyped]
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Filename pattern produced by FFmpeg strftime:
#   %Y-%m-%dT%H-%M-%S_{duration}s.wav
#   Example: 2026-03-26T01-35-00_10s.wav
_FILENAME_TIME_FORMAT = "%Y-%m-%dT%H-%M-%S"


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

    Scans ``{recordings_dir}/*/data/processed/*.wav``.
    Never returns files from ``.buffer/`` directories.

    Args:
        recordings_dir: Root of the Recorder workspace (e.g. ``/data/recorder``).

    Returns:
        Sorted list of absolute paths to promoted WAV files.
    """
    return sorted(recordings_dir.glob("*/data/processed/*.wav"))


def parse_timestamp(filename: str) -> datetime:
    """Parse the recording timestamp from the segment filename.

    Expected format: ``2026-03-26T01-35-00_10s.wav``

    Args:
        filename: WAV filename (basename, not full path).

    Returns:
        UTC datetime of segment start.

    Raises:
        ValueError: If filename does not match expected pattern.
    """
    # Strip extension and duration suffix: "2026-03-26T01-35-00_10s" → "2026-03-26T01-35-00"
    stem = Path(filename).stem
    time_part = stem.rsplit("_", maxsplit=1)[0]
    return datetime.strptime(time_part, _FILENAME_TIME_FORMAT).replace(tzinfo=UTC)


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

    Path structure: ``{recordings_dir}/{sensor_id}/data/processed/file.wav``

    Args:
        wav_path: Absolute path to the WAV file.
        recordings_dir: Root of the Recorder workspace.

    Returns:
        The sensor_id (device name).
    """
    rel = wav_path.relative_to(recordings_dir)
    return rel.parts[0]


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
) -> IndexResult:
    """Scan workspace and register new WAV files in the recordings table.

    Idempotent: existing entries (by ``file_processed``) are skipped.

    Args:
        session: Active async DB session.
        recordings_dir: Root of the Recorder workspace.

    Returns:
        IndexResult with counts of new, skipped, and errored files.
    """
    result = IndexResult()
    wav_files = scan_workspace(recordings_dir)

    for wav_path in wav_files:
        rel_processed = _relative_path(wav_path, recordings_dir)

        try:
            # Idempotency check
            exists = await session.execute(
                text("SELECT 1 FROM recordings WHERE file_processed = :fp LIMIT 1"),
                {"fp": rel_processed},
            )
            if exists.fetchone() is not None:
                result.skipped += 1
                continue

            # Extract metadata
            meta = extract_metadata(wav_path)
            timestamp = parse_timestamp(wav_path.name)
            sensor_id = resolve_sensor_id(wav_path, recordings_dir)

            # Resolve raw file
            raw_path = resolve_raw_path(wav_path)
            rel_raw = _relative_path(raw_path, recordings_dir)
            filesize_raw = os.path.getsize(raw_path) if raw_path.exists() else 0

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
                    "sensor_id": sensor_id,
                    "file_raw": rel_raw,
                    "file_processed": rel_processed,
                    "duration": meta.duration,
                    "sample_rate": meta.sample_rate,
                    "filesize_raw": filesize_raw,
                    "filesize_processed": meta.filesize,
                },
            )
            result.new += 1
            log.info(
                "indexer.indexed",
                file=rel_processed,
                sensor_id=sensor_id,
                duration=meta.duration,
            )

        except Exception:
            result.errors += 1
            result.error_details.append(rel_processed)
            log.exception("indexer.error", file=rel_processed)

    if result.new > 0:
        await session.commit()

    return result
