"""Indexer — Filesystem polling and recording registration.

Scans the Recorder workspace for promoted WAV files in
``{recordings_dir}/*/data/processed/*.wav`` and ``*/data/raw/*.wav``,
extracts metadata via ``soundfile``, and registers new recordings in
the ``recordings`` table.

Idempotent: checks for existing entries by ``processed_path`` (dual-stream)
or ``raw_path`` (raw-only) before insert.
Never touches ``.buffer/`` directories (only promoted, complete segments).

``sample_rate_hz`` and ``channels`` are the microphone's native values, read
from the raw file's header; the processed file is the fallback only when the
raw file is missing.

Cost per cycle: the caller keeps the set of files already known to be
indexed, so a cycle sends one batched existence query for the files it has
not seen yet instead of one query per file on disk.  Without that set the
work would grow with every segment the disk retains.

Supports both dual-stream microphones (raw + processed) and raw-only
microphones where ``processed_enabled=false`` in the microphone profile.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import soundfile as sf
import structlog
from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.models.system import Microphone
from silvasonic.processor.modules.indexer_stats import IndexerStats
from sqlalchemy import bindparam, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Filename pattern produced by FFmpeg pipeline (v0.6+, ADR-0011):
#   Example:  2026-03-26T01-35-00Z_10s_1a2b3c4d_00000000.wav
#   Named while the clock was unsynchronised: ..._00000000_unsynced.wav
_FILENAME_TIME_FORMAT = "%Y-%m-%dT%H-%M-%S"
_FILENAME_REGEX = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)_"
    r"(?P<duration>\d+)s_(?P<run_id>[a-f0-9]{8})_(?P<seq>\d{8})"
    r"(?P<unsynced>_unsynced)?\.wav$"
)


@dataclass
class WavMeta:
    """Metadata extracted from a WAV file."""

    duration_s: float
    sample_rate_hz: int
    channels: int
    size_bytes: int


# Upper bound for the paths sent in one existence query.
_EXISTS_BATCH_SIZE = 1000


@dataclass
class IndexResult:
    """Result of a single indexing run."""

    new: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)


def scan_workspace(recordings_dir: Path) -> list[Path]:
    """Discover all promoted WAV files across all microphone directories.

    Scans both ``{recordings_dir}/*/data/processed/*.wav`` and
    ``*/data/raw/*.wav``. If both exist for the same microphone and
    filename, only the processed version is returned (it is the
    primary indexing artifact for dual-stream microphones).

    Never returns files from ``.buffer/`` directories.

    Args:
        recordings_dir: Root of the Recorder workspace (e.g. ``/data/recorder``).

    Returns:
        Sorted list of absolute paths to promoted WAV files.
    """
    processed = set(recordings_dir.glob("*/data/processed/*.wav"))
    raw = set(recordings_dir.glob("*/data/raw/*.wav"))

    # Deduplicate: if a processed file exists, skip the raw counterpart.
    # Use (workspace_name, filename) as the deduplication key.
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


def is_clock_synced(filename: str) -> bool:
    """Return whether the Recorder named this segment with a synchronised clock.

    A segment carrying the ``_unsynced`` filename suffix (ADR-0011) has a
    timestamp that may be off by however long the device ran without a time
    source (Issue 002).

    Raises:
        ValueError: If filename does not match expected pattern.
    """
    match = _FILENAME_REGEX.match(filename)
    if not match:
        raise ValueError(f"Filename does not match expected pattern: {filename}")
    return match.group("unsynced") is None


def extract_metadata(wav_path: Path) -> WavMeta:
    """Extract metadata from a WAV file.

    Args:
        wav_path: Absolute path to the WAV file.

    Returns:
        WavMeta with duration, sample rate, channels and size.
    """
    info = sf.info(str(wav_path))
    return WavMeta(
        duration_s=info.duration,
        sample_rate_hz=info.samplerate,
        channels=info.channels,
        size_bytes=os.path.getsize(wav_path),
    )


def resolve_workspace_name(wav_path: Path, recordings_dir: Path) -> str:
    """Extract the microphone's workspace directory name from the file path.

    Path structure: ``{recordings_dir}/{workspace_name}/data/{raw|processed}/file.wav``

    Args:
        wav_path: Absolute path to the WAV file.
        recordings_dir: Root of the Recorder workspace.

    Returns:
        The workspace directory name (``microphones.workspace_name``).
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


async def _already_indexed(session: AsyncSession, rel_paths: list[str]) -> set[str]:
    """Return the paths among ``rel_paths`` that the recordings table already holds.

    A path counts as indexed when it equals a row's ``raw_path`` or
    ``processed_path``.  One query per ``_EXISTS_BATCH_SIZE`` paths, served
    by the indexes on both columns.
    """
    found: set[str] = set()
    for i in range(0, len(rel_paths), _EXISTS_BATCH_SIZE):
        rows = await session.execute(
            text(
                "SELECT raw_path, processed_path FROM recordings "
                "WHERE raw_path IN :paths OR processed_path IN :paths"
            ).bindparams(bindparam("paths", expanding=True)),
            {"paths": rel_paths[i : i + _EXISTS_BATCH_SIZE]},
        )
        for raw_path, processed_path in rows.all():
            found.add(raw_path)
            if processed_path is not None:
                found.add(processed_path)
    return found


async def index_recordings(
    session: AsyncSession,
    recordings_dir: Path,
    *,
    errored_files: set[str] | None = None,
    known_files: set[str] | None = None,
    stats: IndexerStats | None = None,
) -> IndexResult:
    """Scan workspace and register new WAV files in the recordings table.

    Idempotent: existing entries (by ``processed_path`` or ``raw_path``
    for raw-only microphones) are skipped.

    Uses ``microphones.workspace_name`` to resolve the filesystem directory
    name to the microphone's ``id``.

    Each new recording is committed on its own, so a failing file never
    rolls back the ones indexed before it in the same cycle.

    Args:
        session: Active DB session
        recordings_dir: Base directory for the workspace
        errored_files: Set of relative paths that failed extraction and should be skipped
        known_files: Relative paths known to be indexed, kept by the caller
            across cycles.  Updated in place: committed files are added and
            files gone from disk are dropped.  ``None`` checks every file.
        stats: Two-Phase Logging stats object

    Returns:
        IndexResult with counts of new, skipped, and errored files.
    """
    result = IndexResult()
    _errored = errored_files or set()
    _known = known_files if known_files is not None else set()
    wav_files = scan_workspace(recordings_dir)
    rel_by_path = {p: _relative_path(p, recordings_dir) for p in wav_files}

    # Forget files the Janitor removed, so the set stays bounded by the disk
    _known.intersection_update(rel_by_path.values())

    candidates: list[Path] = []
    for wav_path, rel_path in rel_by_path.items():
        # Skip files already indexed, or failed extraction in a previous cycle
        if rel_path in _known or rel_path in _errored:
            result.skipped += 1
            if stats:
                stats.record_skipped()
            continue
        candidates.append(wav_path)

    if not candidates:
        return result

    in_db = await _already_indexed(session, [rel_by_path[p] for p in candidates])
    # Release the read transaction: metadata extraction below must not hold the database write
    # lock (ADR-0037).  Nothing was written.
    await session.rollback()
    microphone_ids: dict[str, uuid.UUID | None] = {}

    for wav_path in candidates:
        is_raw = _is_raw_path(wav_path)
        rel_path = rel_by_path[wav_path]

        if rel_path in in_db:
            _known.add(rel_path)
            result.skipped += 1
            if stats:
                stats.record_skipped()
            continue

        try:
            workspace_name = resolve_workspace_name(wav_path, recordings_dir)

            # Resolve microphone: look up by workspace_name (cross-service contract)
            if workspace_name not in microphone_ids:
                microphone_row = await session.execute(
                    select(Microphone.id)
                    .where(Microphone.workspace_name == workspace_name)
                    .limit(1)
                )
                row = microphone_row.fetchone()
                microphone_ids[workspace_name] = row[0] if row is not None else None
                await session.rollback()  # release the lock before file I/O
            microphone_id = microphone_ids[workspace_name]
            if microphone_id is None:
                result.skipped += 1
                if stats:
                    stats.record_skipped()
                log.info(
                    "indexer.microphone_not_registered",
                    file=rel_path,
                    workspace_name=workspace_name,
                )
                continue

            # Extract metadata
            meta = extract_metadata(wav_path)
            timestamp = parse_timestamp(wav_path.name)
            clock_synced = is_clock_synced(wav_path.name)

            # Resolve file paths for both streams
            if is_raw:
                # Raw-only microphone: no processed file
                rel_raw = rel_path
                rel_processed = None
                raw_size_bytes = meta.size_bytes
                processed_size_bytes = 0
                native = meta
            else:
                # Dual-stream microphone: processed is primary, derive raw
                rel_processed = rel_path
                raw_file = resolve_raw_path(wav_path)
                rel_raw = _relative_path(raw_file, recordings_dir)
                processed_size_bytes = meta.size_bytes
                if raw_file.exists():
                    # The raw header carries the microphone's native rate
                    native = extract_metadata(raw_file)
                    raw_size_bytes = native.size_bytes
                else:
                    native = meta
                    raw_size_bytes = 0

            # Insert new recording
            await session.execute(
                insert(Recording).values(
                    started_at=timestamp,
                    microphone_id=microphone_id,
                    raw_path=rel_raw,
                    processed_path=rel_processed,
                    duration_s=meta.duration_s,
                    sample_rate_hz=native.sample_rate_hz,
                    channels=native.channels,
                    raw_size_bytes=raw_size_bytes,
                    processed_size_bytes=processed_size_bytes,
                    clock_synced=clock_synced,
                )
            )
            await session.commit()
            _known.add(rel_path)
            result.new += 1
            if stats:
                stats.record_indexed(
                    rel_path=rel_path,
                    microphone_id=microphone_id,
                    duration_s=meta.duration_s,
                )
            else:
                log.info(
                    "indexer.indexed",
                    file=rel_path,
                    microphone_id=str(microphone_id),
                    duration_s=meta.duration_s,
                )

        except Exception:
            await session.rollback()
            result.errors += 1
            result.error_details.append(rel_path)
            if stats:
                stats.record_error(rel_path)
            else:
                log.exception("indexer.error", file=rel_path)

    return result
