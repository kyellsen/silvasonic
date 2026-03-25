"""Audio capture pipeline — sounddevice + soundfile (ADR-0011).

Phase 1: Single-stream (Raw) capture with segmented WAV output.
Phase 4 will extend this to Dual Stream (Raw + Processed via soxr).

Architecture:
    - ``PipelineConfig``: Validated capture parameters from MicrophoneProfile
    - ``SegmentWriter``: Manages a single WAV file segment in .buffer/
    - ``AudioPipeline``: Orchestrates InputStream → SegmentWriter rotation

The InputStream callback runs in the PortAudio C thread.  It writes
audio data to a thread-safe ``queue.Queue``.  The async ``run()``
coroutine drains the queue and writes to ``soundfile`` in the event
loop thread — this avoids blocking the PortAudio callback with file I/O.
"""

from __future__ import annotations

import contextlib
import os
import queue
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import sounddevice as sd
import soundfile as sf
import structlog
from pydantic import BaseModel, Field, PositiveInt
from silvasonic.core.schemas.devices import MicrophoneProfile

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Format mapping: ADR-0011 format strings → numpy/soundfile types
# ---------------------------------------------------------------------------
_FORMAT_MAP: dict[str, tuple[str, str]] = {
    # ADR format → (numpy dtype, soundfile subtype)
    "S16LE": ("int16", "PCM_16"),
    "S24LE": ("int32", "PCM_24"),  # 24-bit packed into int32
    "S32LE": ("int32", "PCM_32"),
}

# Default format for development / fallback
_DEFAULT_FORMAT: Literal["S16LE", "S24LE", "S32LE"] = "S16LE"


def _ensure_alsa_hostapi() -> None:
    """Verify that the ALSA host API is available in PortAudio.

    When an explicit ``hw:X,0`` device string is passed to
    ``sd.InputStream(device=...)``, PortAudio routes through ALSA
    directly.  This helper validates ALSA availability early and logs
    a warning if it's missing (e.g. inside a container without ALSA).

    Must be called **before** opening any ``sd.InputStream``.
    """
    for _idx, api in enumerate(sd.query_hostapis()):
        if api["name"] == "ALSA":
            log.debug("pipeline.alsa_hostapi_available", index=_idx)
            return
    log.warning("pipeline.alsa_hostapi_not_found")  # pragma: no cover — no ALSA in CI


# ---------------------------------------------------------------------------
# PipelineConfig
# ---------------------------------------------------------------------------
class PipelineConfig(BaseModel):
    """Validated capture parameters for the audio pipeline.

    Can be built from a :class:`MicrophoneProfile` or from defaults
    (for development / unknown microphones).
    """

    sample_rate: PositiveInt = Field(default=48000, description="Capture sample rate (Hz)")
    channels: PositiveInt = Field(default=1, description="Number of audio channels")
    format: Literal["S16LE", "S24LE", "S32LE"] = Field(default="S16LE", description="Sample format")
    chunk_size: PositiveInt = Field(default=4096, description="Frames per callback block")
    segment_duration_s: PositiveInt = Field(default=10, description="Segment length (seconds)")
    gain_db: float = Field(default=0.0, description="Software gain in dB")

    @classmethod
    def from_profile(cls, profile: MicrophoneProfile) -> PipelineConfig:
        """Build pipeline config from a validated MicrophoneProfile.

        Extracts audio, processing, and stream settings from the profile
        into a flat config suitable for the pipeline.
        """
        return cls(
            sample_rate=profile.audio.sample_rate,
            channels=profile.audio.channels,
            format=profile.audio.format,
            chunk_size=profile.processing.chunk_size,
            segment_duration_s=profile.stream.segment_duration_s,
            gain_db=profile.processing.gain_db,
        )

    @property
    def numpy_dtype(self) -> str:
        """Return the numpy dtype string for this format."""
        return _FORMAT_MAP.get(self.format, _FORMAT_MAP[_DEFAULT_FORMAT])[0]

    @property
    def soundfile_subtype(self) -> str:
        """Return the soundfile subtype string for this format."""
        return _FORMAT_MAP.get(self.format, _FORMAT_MAP[_DEFAULT_FORMAT])[1]

    @property
    def frames_per_segment(self) -> int:
        """Total frames per segment (sample_rate x segment_duration_s)."""
        return self.sample_rate * self.segment_duration_s


# ---------------------------------------------------------------------------
# SegmentWriter
# ---------------------------------------------------------------------------
def _segment_filename(timestamp: datetime, duration_s: int) -> str:
    """Generate a segment filename from timestamp and duration.

    Format: ``{ISO-timestamp}_{duration}s.wav``
    Example: ``2026-03-25T14-30-00_{10}s.wav``

    The timestamp uses hyphens instead of colons for filesystem safety.
    """
    ts = timestamp.strftime("%Y-%m-%dT%H-%M-%S")
    return f"{ts}_{duration_s}s.wav"


class SegmentWriter:
    """Manage a single WAV file segment in ``.buffer/raw/``.

    Opens a soundfile for writing, accepts audio data via ``write()``,
    and on ``close_and_promote()`` atomically moves the completed file
    from ``.buffer/raw/`` to ``data/raw/``.

    Args:
        buffer_dir: Path to ``.buffer/raw/`` directory.
        data_dir: Path to ``data/raw/`` directory.
        config: Pipeline configuration (sample rate, format, channels).
    """

    def __init__(
        self,
        buffer_dir: Path,
        data_dir: Path,
        config: PipelineConfig,
    ) -> None:
        """Initialize and open a new segment file for writing."""
        self._config = config
        self._data_dir = data_dir
        self._timestamp = datetime.now(UTC)
        self._filename = _segment_filename(self._timestamp, config.segment_duration_s)
        self._buffer_path = buffer_dir / self._filename
        self._data_path = data_dir / self._filename
        self._frames_written = 0
        self._closed = False

        self._sf = sf.SoundFile(
            str(self._buffer_path),
            mode="w",
            samplerate=config.sample_rate,
            channels=config.channels,
            subtype=config.soundfile_subtype,
        )
        log.debug(
            "segment.opened",
            path=str(self._buffer_path),
            sample_rate=config.sample_rate,
        )

    @property
    def frames_written(self) -> int:
        """Number of audio frames written to this segment."""
        return self._frames_written

    @property
    def is_full(self) -> bool:
        """Return ``True`` if segment has reached its target duration."""
        return self._frames_written >= self._config.frames_per_segment

    @property
    def is_closed(self) -> bool:
        """Return ``True`` if the segment has been closed."""
        return self._closed

    def write(self, data: np.ndarray) -> None:
        """Write audio frames to the segment.

        Args:
            data: Audio data array (frames x channels).
        """
        if self._closed:
            return
        self._sf.write(data)
        self._frames_written += len(data)

    def close_and_promote(self) -> Path | None:
        """Close the WAV file and atomically move it to ``data/raw/``.

        Uses ``os.replace()`` for atomic promotion — the Processor
        will only ever see complete files in ``data/``.

        Returns:
            Path to the promoted file, or ``None`` if already closed.
        """
        if self._closed:
            return None

        self._closed = True
        self._sf.close()

        try:
            os.replace(str(self._buffer_path), str(self._data_path))
            log.info(
                "segment.promoted",
                filename=self._filename,
                frames=self._frames_written,
                duration_s=round(self._frames_written / self._config.sample_rate, 2),
            )
            return self._data_path
        except OSError:  # pragma: no cover — OS-level os.replace() failure
            log.exception("segment.promote_failed", filename=self._filename)
            return None

    def close_discard(self) -> None:
        """Close without promoting (e.g. on error or empty segment)."""
        if self._closed:
            return
        self._closed = True
        self._sf.close()
        # Remove the incomplete buffer file
        with contextlib.suppress(OSError):
            self._buffer_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# AudioPipeline
# ---------------------------------------------------------------------------

# Sentinel to signal the pipeline loop to stop
_STOP = object()


class AudioPipeline:
    """Orchestrate audio capture with segmented WAV output.

    Uses ``sounddevice.InputStream`` with a callback that pushes audio
    chunks to a ``queue.Queue``.  The ``run()`` method drains the queue
    and writes data to ``SegmentWriter``, rotating segments when full.

    Args:
        config: Pipeline configuration.
        workspace: Workspace root path (contains ``data/`` and ``.buffer/``).
        device: ALSA device string (e.g. ``"hw:1,0"``).
    """

    def __init__(
        self,
        config: PipelineConfig,
        workspace: Path,
        device: str = "hw:1,0",
    ) -> None:
        """Initialize the pipeline (does NOT start recording)."""
        self._config = config
        self._workspace = workspace
        self._device = device
        self._buffer_dir = workspace / ".buffer" / "raw"
        self._data_dir = workspace / "data" / "raw"
        self._stream: sd.InputStream | None = None
        self._writer: SegmentWriter | None = None
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=64)
        self._active = False
        self._lock = threading.Lock()
        self._xrun_count = 0

    @property
    def is_active(self) -> bool:
        """Return ``True`` if the pipeline is currently recording."""
        return self._active

    @property
    def xrun_count(self) -> int:
        """Number of xruns (buffer overflows) detected."""
        return self._xrun_count

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        """PortAudio callback — runs in the audio thread.

        Pushes audio data to the queue for processing in the main thread.
        Never blocks — drops data if the queue is full (xrun scenario).
        """
        if status.input_overflow:
            self._xrun_count += 1

        try:
            self._queue.put_nowait(indata.copy())
        except queue.Full:
            self._xrun_count += 1
            # Throttle: log first occurrence, then every 100th to avoid spam.
            # At 384 kHz with 4096-frame chunks, ~94 callbacks/s overflow once
            # the 64-slot queue is full — unthrottled this produces 400+ warnings
            # in a 5s recording.  The total count is always in pipeline.stopped.
            if self._xrun_count == 1 or self._xrun_count % 100 == 0:
                log.warning(
                    "pipeline.queue_full",
                    xrun_count=self._xrun_count,
                    hint="consumer too slow — audio data dropped",
                )

    def start(self) -> None:
        """Open the audio stream and start recording.

        Creates the initial ``SegmentWriter`` and opens the
        ``sounddevice.InputStream``.  The stream starts pushing
        audio data to the internal queue immediately.

        Raises:
            sd.PortAudioError: If the audio device cannot be opened.
        """
        _ensure_alsa_hostapi()

        self._writer = SegmentWriter(
            self._buffer_dir,
            self._data_dir,
            self._config,
        )

        self._stream = sd.InputStream(
            device=self._device,
            samplerate=self._config.sample_rate,
            channels=self._config.channels,
            dtype=self._config.numpy_dtype,
            blocksize=self._config.chunk_size,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._active = True

        log.info(
            "pipeline.started",
            device=self._device,
            sample_rate=self._config.sample_rate,
            channels=self._config.channels,
            format=self._config.format,
            segment_s=self._config.segment_duration_s,
        )

    def _apply_gain(self, data: np.ndarray) -> np.ndarray:
        """Apply software gain if configured.

        Args:
            data: Audio data array.

        Returns:
            Gained audio data (or original if gain is 0 dB).
        """
        if self._config.gain_db == 0.0:
            return data

        gain_linear = 10 ** (self._config.gain_db / 20.0)
        return (data.astype(np.float64) * gain_linear).astype(data.dtype)

    def _rotate_segment(self) -> None:
        """Close the current segment and open a new one."""
        if self._writer is not None:
            self._writer.close_and_promote()

        self._writer = SegmentWriter(
            self._buffer_dir,
            self._data_dir,
            self._config,
        )

    def process_chunk(self, data: np.ndarray) -> None:
        """Process a single audio chunk from the queue.

        Applies gain, writes to the current segment, and rotates
        the segment when it reaches the target duration.

        Args:
            data: Audio data array (frames x channels).
        """
        if self._writer is None:  # pragma: no cover — defensive guard, race condition only
            return

        gained = self._apply_gain(data)
        self._writer.write(gained)

        if self._writer.is_full:
            self._rotate_segment()

    def drain_queue(self) -> int:
        """Drain all available audio chunks from the queue.

        Returns:
            Number of chunks processed.
        """
        count = 0
        while True:
            try:
                data = self._queue.get_nowait()
                if data is _STOP:  # pragma: no cover — reserved for Phase 5 watchdog
                    break
                self.process_chunk(data)
                count += 1
            except queue.Empty:
                break
        return count

    def stop(self) -> None:
        """Stop recording and finalize the current segment.

        Closes the audio stream, drains remaining data from the queue,
        and promotes the final segment to ``data/raw/``.
        """
        self._active = False

        # Stop the audio stream first
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # pragma: no cover — PortAudio stream close failure
                log.exception("pipeline.stream_close_failed")
            self._stream = None

        # Drain remaining data
        self.drain_queue()

        # Close and promote the final segment
        if self._writer is not None:
            if self._writer.frames_written > 0:
                self._writer.close_and_promote()
            else:
                self._writer.close_discard()
            self._writer = None

        log.info("pipeline.stopped", xruns=self._xrun_count)
