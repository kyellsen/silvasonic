"""FLAC compression for audio files before uploading.

Uses the system ffmpeg binary to compress WAV to FLAC transparently.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

log = structlog.get_logger()


class FlacEncodingError(Exception):
    """Raised when ffmpeg fails to encode the audio file."""


async def encode_wav_to_flac(wav_path: Path, output_dir: Path) -> Path:
    """Encode a WAV file to FLAC using ffmpeg (compression level 5).

    Args:
        wav_path: Path to the original WAV file.
        output_dir: Directory to place the resulting FLAC file.

    Returns:
        Path to the completed FLAC file.

    Raises:
        RuntimeError: If WAV file does not exist.
        FlacEncodingError: If ffmpeg execution fails.
    """
    if not wav_path.exists():
        msg = f"File not found: {wav_path}"
        raise RuntimeError(msg)

    flac_path = output_dir / wav_path.with_suffix(".flac").name

    # Create directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",  # Overwrite
        "-i",
        str(wav_path),
        "-c:a",
        "flac",
        "-compression_level",
        "5",
        str(flac_path),
    ]

    log.debug("flac_encoder.start", source=wav_path.name, target=flac_path.name)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        err_msg = stderr.decode("utf-8", errors="replace")
        log.error("flac_encoder.failed", source=wav_path.name, code=proc.returncode, error=err_msg)

        # Cleanup partial FLAC file
        if flac_path.exists():
            flac_path.unlink()

        msg = f"ffmpeg failed with exit code {proc.returncode}:\n{err_msg}"
        raise FlacEncodingError(msg)

    # Validate output
    if not flac_path.exists() or flac_path.stat().st_size == 0:
        if flac_path.exists():
            flac_path.unlink()
        msg = "ffmpeg succeeded but output file is missing or empty"
        raise FlacEncodingError(msg)

    log.debug("flac_encoder.success", source=wav_path.name, size=flac_path.stat().st_size)
    return flac_path
