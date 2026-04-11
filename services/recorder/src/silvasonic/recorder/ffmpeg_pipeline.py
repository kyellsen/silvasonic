"""FFmpeg-based audio capture pipeline (ADR-0024).

Dual Stream Architecture (ADR-0011):
    - **Raw**: Hardware-native sample rate & bit depth → ``data/raw/``
    - **Processed**: Resampled to 48 kHz / S16LE via FFmpeg → ``data/processed/``

Architecture:
    - ``FFmpegConfig``: Validated capture parameters → FFmpeg command builder
    - ``SegmentPromoter``: Polls ``.buffer/`` directory → atomic promotion
    - ``FFmpegPipeline``: Manages FFmpeg subprocess + dual promoter threads

FFmpeg runs as a separate OS process.  Python never touches audio data —
no GIL, no GC pauses, no queue contention.  The ``SegmentPromoter``
polls ``.buffer/`` for completed segments and promotes them to
``data/`` via ``os.replace()`` (POSIX-atomic).

Completeness Signal:
    FFmpeg's segment muxer closes segment N *before* opening N+1.
    Therefore, if ≥2 files exist in ``.buffer/{stream}/``, all but the
    newest are guaranteed complete.  After FFmpeg exits (SIGINT), **all**
    remaining files are complete.  No segment-list CSV needed.
"""

from __future__ import annotations

import datetime
import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import structlog
from pydantic import BaseModel, Field, PositiveInt
from silvasonic.core.schemas.recorder import RecorderRuntimeConfig

if TYPE_CHECKING:
    from silvasonic.recorder.recording_stats import RecordingStats

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Processed stream target (ADR-0011) — DRY constants (single source of truth)
# ---------------------------------------------------------------------------
PROCESSED_SAMPLE_RATE: int = 48000
"""Target sample rate for the processed stream (Hz). Always 48 kHz."""

PROCESSED_FORMAT: str = "S16LE"
"""Target sample format for the processed stream. Always 16-bit signed LE."""

# ---------------------------------------------------------------------------
# Format mapping: ADR-0011 format strings → FFmpeg codec names
# ---------------------------------------------------------------------------
_FFMPEG_CODEC_MAP: dict[str, str] = {
    "S16LE": "pcm_s16le",
    "S24LE": "pcm_s24le",
    "S32LE": "pcm_s32le",
}

# ALSA format names for FFmpeg input
_ALSA_FORMAT_MAP: dict[str, str] = {
    "S16LE": "s16",
    "S24LE": "s32",  # 24-bit captured as 32-bit container via ALSA
    "S32LE": "s32",
}


# ---------------------------------------------------------------------------
# FFmpegConfig
# ---------------------------------------------------------------------------
class FFmpegConfig(BaseModel):
    """Validated capture parameters for the FFmpeg pipeline.

    Can be built from a :class:`MicrophoneProfile` or from defaults
    (for development / unknown microphones).
    """

    sample_rate: PositiveInt = Field(default=48000, description="Capture sample rate (Hz)")
    channels: PositiveInt = Field(default=1, description="Number of audio channels")
    format: Literal["S16LE", "S24LE", "S32LE"] = Field(default="S16LE", description="Sample format")
    segment_duration_s: PositiveInt = Field(default=10, description="Segment length (seconds)")
    gain_db: float = Field(default=0.0, description="Software gain in dB")
    raw_enabled: bool = Field(default=True, description="Write raw stream")
    processed_enabled: bool = Field(default=True, description="Write processed stream")

    @classmethod
    def from_injected_config(cls, config: RecorderRuntimeConfig) -> FFmpegConfig:
        """Build config from a validated controller-injected runtime config."""
        return cls(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
            format=config.audio.format,
            segment_duration_s=config.stream.segment_duration_s,
            gain_db=config.processing.gain_db,
            raw_enabled=config.stream.raw_enabled,
            processed_enabled=config.stream.processed_enabled,
        )

    @property
    def ffmpeg_codec(self) -> str:
        """Return the FFmpeg codec name for this format."""
        return _FFMPEG_CODEC_MAP[self.format]

    @property
    def alsa_format(self) -> str:
        """Return the ALSA sample format string for FFmpeg input."""
        return _ALSA_FORMAT_MAP[self.format]

    @property
    def ffmpeg_volume_filter(self) -> str | None:
        """Return the FFmpeg volume filter string, or None if gain is 0 dB."""
        if self.gain_db == 0.0:
            return None
        return f"volume={self.gain_db}dB"

    def build_ffmpeg_args(
        self,
        device: str,
        workspace: Path,
        run_id: str,
        *,
        mock_source: bool = False,
        mock_file: Path | None = None,
        ffmpeg_binary: str = "ffmpeg",
        loglevel: str = "warning",
    ) -> list[str]:
        """Build the complete FFmpeg command line.

        Args:
            device: ALSA device string (e.g. ``"hw:2,0"``).
            workspace: Workspace root path.
            run_id: Unique 8-character hex ID for collision-proof filenames.
            mock_source: Use lavfi sine generator instead of ALSA.
            mock_file: Optional explicit wav file to use in mock source mode
                (e.g. tests/fixtures/audio/...)
            ffmpeg_binary: Path to the FFmpeg binary.
            loglevel: FFmpeg log level.

        Returns:
            Complete argument list for ``subprocess.Popen``.
        """
        cmd: list[str] = [
            ffmpeg_binary,
            "-y",
            "-nostdin",
            "-loglevel",
            loglevel,
        ]

        # Input source
        if mock_source:
            if mock_file:
                cmd.extend(
                    [
                        "-stream_loop",
                        "-1",
                        "-i",
                        str(mock_file),
                    ]
                )
            else:
                cmd.extend(
                    [
                        "-re",  # Force real-time processing (lavfi has no I/O constraint)
                        "-f",
                        "lavfi",
                        "-i",
                        f"sine=frequency=440:sample_rate={self.sample_rate}:duration=86400",
                    ]
                )
        else:
            cmd.extend(
                [
                    "-f",
                    "alsa",
                    "-sample_rate",
                    str(self.sample_rate),
                    "-channels",
                    str(self.channels),
                    "-sample_fmt",
                    self.alsa_format,
                    "-i",
                    device,
                ]
            )

        # Audio filter (gain)
        volume_filter = self.ffmpeg_volume_filter
        if volume_filter:
            cmd.extend(["-af", volume_filter])

        seg_time = str(self.segment_duration_s)

        # Output 1: Raw stream
        if self.raw_enabled:
            raw_buffer = workspace / ".buffer" / "raw"
            cmd.extend(
                [
                    "-map",
                    "0:a",
                    "-c:a",
                    self.ffmpeg_codec,
                    "-f",
                    "segment",
                    "-segment_time",
                    seg_time,
                    "-segment_format",
                    "wav",
                    "-reset_timestamps",
                    "1",
                    str(raw_buffer) + f"/{run_id}_%08d.wav",
                ]
            )

        # Output 2: Processed stream (resampled to 48 kHz / S16LE)
        if self.processed_enabled:
            proc_buffer = workspace / ".buffer" / "processed"
            cmd.extend(
                [
                    "-map",
                    "0:a",
                    "-ar",
                    str(PROCESSED_SAMPLE_RATE),
                    "-c:a",
                    _FFMPEG_CODEC_MAP[PROCESSED_FORMAT],
                    "-f",
                    "segment",
                    "-segment_time",
                    seg_time,
                    "-segment_format",
                    "wav",
                    "-reset_timestamps",
                    "1",
                    str(proc_buffer) + f"/{run_id}_%08d.wav",
                ]
            )

        return cmd


# ---------------------------------------------------------------------------
# TimestampRegistry
# ---------------------------------------------------------------------------
class TimestampRegistry:
    """Provides thread-safe, monotonically-increasing UTC timestamps.

    Used by SegmentPromoter to ensure that raw and processed streams
    receive the exact identical timestamp string for the same segment
    sequence, even if CPU scheduling delays one promoter thread.
    """

    def __init__(self, max_size: int = 128) -> None:
        """Initialize the thread-safe registry with an eviction limit."""
        self._times: dict[tuple[str, int], str] = {}
        self._lock = threading.Lock()
        self._max_size = max_size

    def get_timestamp(self, key: tuple[str, int]) -> str:
        """Get or generate the UTC timestamp for (run_id, seq)."""
        with self._lock:
            if key not in self._times:
                # Evict oldest if we hit the safe limit
                if len(self._times) >= self._max_size:
                    oldest_key = next(iter(self._times))
                    del self._times[oldest_key]
                # Format: YYYY-MM-DDTHH-MM-SSZ
                self._times[key] = datetime.datetime.now(datetime.UTC).strftime(
                    "%Y-%m-%dT%H-%M-%SZ"
                )
            return self._times[key]


# ---------------------------------------------------------------------------
# SegmentPromoter
# ---------------------------------------------------------------------------
class SegmentPromoter(threading.Thread):
    """Poll ``.buffer/`` directory and promote completed segments.

    FFmpeg's segment muxer closes segment N before opening N+1.
    If ≥2 WAV files exist in the buffer directory, all but the newest
    are guaranteed complete.  Each completed file is atomically moved
    to ``data/`` via ``os.replace()``.

    After ``stop()`` is called, a **final pass** promotes all remaining
    files (FFmpeg has exited, so every file is complete).

    The Processor/Indexer (v0.5.0) polls ``data/`` for new WAVs —
    atomic promotion ensures it never sees partially-written files.

    Args:
        buffer_dir: Source directory (``.buffer/raw/`` or ``.buffer/processed/``).
        data_dir: Target directory (``data/raw/`` or ``data/processed/``).
        stream_name: Stream identifier for logging (``"raw"`` or ``"processed"``).
        poll_interval: Seconds between directory polls.
    """

    def __init__(
        self,
        buffer_dir: Path,
        data_dir: Path,
        stream_name: str = "raw",
        segment_duration_s: int = 10,
        registry: TimestampRegistry | None = None,
        poll_interval: float = 0.5,
        stats: RecordingStats | None = None,
    ) -> None:
        """Initialize the promoter thread."""
        super().__init__(name=f"segment-promoter-{stream_name}", daemon=True)
        self._buffer_dir = buffer_dir
        self._data_dir = data_dir
        self._stream_name = stream_name
        self._segment_duration_s = segment_duration_s
        self._registry = registry or TimestampRegistry()
        self._poll_interval = poll_interval
        self._stats = stats
        self._running = False
        self._promoted_count = 0
        self._promoted_lock = threading.Lock()

    @property
    def segments_promoted(self) -> int:
        """Total number of segments promoted to ``data/``."""
        with self._promoted_lock:
            return self._promoted_count

    def stop(self) -> None:
        """Signal the promoter to stop."""
        self._running = False

    def run(self) -> None:
        """Poll loop: scan buffer directory, promote completed segments."""
        self._running = True
        log.info("segment_promoter.started", stream=self._stream_name)

        while self._running:
            self._poll_and_promote()  # pragma: no cover — integration-tested
            time.sleep(self._poll_interval)  # pragma: no cover — integration-tested

        # Final promotion pass — FFmpeg has exited, ALL files are complete
        self._promote_all()
        log.info(
            "segment_promoter.stopped",
            stream=self._stream_name,
            promoted=self.segments_promoted,
        )

    def _poll_and_promote(self) -> None:
        """Promote completed segments from ``.buffer/`` to ``data/``.

        FFmpeg closes segment N before opening N+1.  Therefore, if ≥2
        files exist in ``.buffer/``, all but the newest (the active
        segment being written) are complete and safe to promote.
        """
        files = sorted(self._buffer_dir.glob("*.wav"))
        if len(files) < 2:
            return  # 0 or 1 file — nothing complete yet

        # All except the newest (actively being written by FFmpeg)
        for src in files[:-1]:
            self._promote_segment(src)

    def _promote_all(self) -> None:
        """Promote ALL remaining files (called after FFmpeg exits).

        After FFmpeg has been stopped via SIGINT and the process has
        exited, every remaining file in ``.buffer/`` is complete
        (FFmpeg finalized the WAV header on shutdown).
        """
        for src in sorted(self._buffer_dir.glob("*.wav")):
            self._promote_segment(src)

    def _promote_segment(self, src: Path) -> None:
        """Atomically move a segment from .buffer/ to data/ taking safe timestamps."""
        # filename format in .buffer/: {run_id}_{seq}.wav
        stem = src.stem
        try:
            run_id, seq_str = stem.split("_", 1)
            seq = int(seq_str)
        except ValueError:
            # Fallback for completely invalid files, just move them as-is without crashing
            target_name = src.name
            log.warning("segment.invalid_name", filename=src.name, stream=self._stream_name)
        else:
            # Generate deterministic identical timestamp for this exact (run_id, seq) pair
            ts_str = self._registry.get_timestamp((run_id, seq))
            target_name = f"{ts_str}_{self._segment_duration_s}s_{run_id}_{seq:08d}.wav"

        dst = self._data_dir / target_name

        try:
            file_size = src.stat().st_size
            os.replace(str(src), str(dst))
            with self._promoted_lock:
                self._promoted_count += 1
            if self._stats is not None:
                self._stats.record_promotion(  # pragma: no cover — integration-tested
                    self._stream_name,
                    src.name,
                    file_size,
                )
            else:
                log.info(
                    "segment.promoted",
                    stream=self._stream_name,
                    filename=src.name,
                    size_bytes=file_size,
                    total=self.segments_promoted,
                )
        except OSError:  # pragma: no cover — defensive
            if self._stats is not None:  # pragma: no cover
                self._stats.record_error(  # pragma: no cover
                    self._stream_name,
                    src.name,
                )
            else:
                log.exception(  # pragma: no cover — defensive
                    "segment.promote_failed",
                    stream=self._stream_name,
                    filename=src.name,
                )


# ---------------------------------------------------------------------------
# FFmpegPipeline
# ---------------------------------------------------------------------------
class FFmpegPipeline:
    """Manage FFmpeg subprocess for dual-stream audio capture (ADR-0024).

    Produces two simultaneous output streams from a single capture
    (ADR-0011):

    - **Raw**: Hardware-native sample rate & bit depth → ``data/raw/``
    - **Processed**: Resampled to 48 kHz / S16LE → ``data/processed/``

    FFmpeg writes segments to ``.buffer/``.  ``SegmentPromoter`` threads
    poll the buffer directory and atomically promote completed segments
    to ``data/`` via ``os.replace()``.

    Args:
        config: Pipeline configuration.
        workspace: Workspace root path.
        device: ALSA device string (e.g. ``"hw:1,0"``).
        mock_source: Use FFmpeg lavfi sine generator instead of ALSA.
        ffmpeg_binary: Path to the FFmpeg binary.
        ffmpeg_loglevel: FFmpeg log level.
    """

    def __init__(
        self,
        config: FFmpegConfig,
        workspace: Path,
        device: str = "hw:1,0",
        *,
        mock_source: bool = False,
        mock_file: Path | None = None,
        ffmpeg_binary: str = "ffmpeg",
        ffmpeg_loglevel: str = "warning",
        stats: RecordingStats | None = None,
    ) -> None:
        """Initialize the pipeline (does NOT start recording)."""
        self._config = config
        self._workspace = workspace
        self._device = device
        self._mock_source = mock_source
        self._mock_file = mock_file
        self._ffmpeg_binary = ffmpeg_binary
        self._ffmpeg_loglevel = ffmpeg_loglevel
        self._stats = stats

        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr_thread: threading.Thread | None = None
        self._promoters: list[SegmentPromoter] = []
        self._active = False
        self._stderr_errors: list[str] = []
        self._stderr_lock = threading.Lock()
        self._final_promoted = 0  # cached count surviving past stop()
        self._last_returncode: int | None = None

    @property
    def is_active(self) -> bool:
        """Return ``True`` if FFmpeg is currently running."""
        return self._active and self._proc is not None and self._proc.poll() is None

    @property
    def segments_promoted(self) -> int:
        """Total segments promoted across all streams."""
        if self._promoters:
            return sum(p.segments_promoted for p in self._promoters)
        return self._final_promoted

    @property
    def stderr_errors(self) -> list[str]:
        """FFmpeg stderr lines containing warnings/errors."""
        with self._stderr_lock:
            return list(self._stderr_errors)

    @property
    def ffmpeg_pid(self) -> int | None:
        """PID of the FFmpeg subprocess, or ``None``."""
        return self._proc.pid if self._proc else None

    @property
    def returncode(self) -> int | None:
        """Return code of the last FFmpeg process, or ``None``."""
        if self._proc is not None:
            return self._proc.poll()
        return self._last_returncode

    def start(self) -> None:
        """Start FFmpeg and segment promoter threads.

        Can be called again after ``stop()`` to restart the pipeline
        (re-entrant lifecycle, used by ``RecordingWatchdog``).

        Raises:
            FileNotFoundError: If the FFmpeg binary is not found.
            subprocess.SubprocessError: If FFmpeg fails to start.
        """
        # Clear stale state from previous run (re-entrant support)
        with self._stderr_lock:
            self._stderr_errors.clear()

        # Generate a unique run ID for this pipeline execution to prevent fast-restart collisions
        # 8 Hex Chars (32-bit) is perfect for short-term directory disambiguation
        self.run_id = uuid.uuid4().hex[:8]
        # Refresh the shared registry for promoters to map sequence numbers to wall-clock time
        self._timestamp_registry = TimestampRegistry()

        cmd = self._config.build_ffmpeg_args(
            device=self._device,
            workspace=self._workspace,
            run_id=self.run_id,
            mock_source=self._mock_source,
            mock_file=self._mock_file,
            ffmpeg_binary=self._ffmpeg_binary,
            loglevel=self._ffmpeg_loglevel,
        )

        log.info(
            "pipeline.starting",
            device=self._device if not self._mock_source else "mock (lavfi)",
            run_id=self.run_id,
            sample_rate=self._config.sample_rate,
            channels=self._config.channels,
            format=self._config.format,
            segment_s=self._config.segment_duration_s,
            raw_enabled=self._config.raw_enabled,
            processed_enabled=self._config.processed_enabled,
            processed_sr=PROCESSED_SAMPLE_RATE,
            mock_source=self._mock_source,
            cmd=" ".join(cmd),
        )

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Start stderr monitoring thread
        self._stderr_thread = threading.Thread(
            target=self._monitor_stderr,
            name="ffmpeg-stderr-monitor",
            daemon=True,
        )
        self._stderr_thread.start()

        # Start segment promoters for enabled streams
        self._promoters = []
        for stream, enabled in (
            ("raw", self._config.raw_enabled),
            ("processed", self._config.processed_enabled),
        ):
            if enabled:
                p = SegmentPromoter(
                    buffer_dir=self._workspace / ".buffer" / stream,
                    data_dir=self._workspace / "data" / stream,
                    stream_name=stream,
                    segment_duration_s=self._config.segment_duration_s,
                    registry=self._timestamp_registry,
                    stats=self._stats,
                )
                p.start()
                self._promoters.append(p)

        self._active = True
        log.info("pipeline.started", ffmpeg_pid=self._proc.pid)

    def _monitor_stderr(self) -> None:
        """Read FFmpeg stderr and capture warnings/errors."""
        if self._proc is None or self._proc.stderr is None:
            return  # pragma: no cover

        for raw_line in self._proc.stderr:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue  # pragma: no cover — integration-tested

            # Log all FFmpeg output at debug level
            log.debug("ffmpeg.stderr", line=line)

            # Capture warnings and errors for health reporting
            if any(kw in line.lower() for kw in ("error", "overrun", "xrun", "warning")):
                with self._stderr_lock:
                    self._stderr_errors.append(line)
                    # Keep only last 100 errors to prevent memory growth
                    if len(self._stderr_errors) > 100:
                        self._stderr_errors = self._stderr_errors[-50:]  # pragma: no cover

    def stop(self) -> None:
        """Stop FFmpeg gracefully and promote remaining segments.

        Sends SIGINT for a clean shutdown (FFmpeg finalizes the last
        WAV header).  Falls back to SIGTERM/SIGKILL if FFmpeg does
        not exit within the timeout.
        """
        self._active = False

        if self._proc is not None and self._proc.poll() is None:
            try:
                # SIGINT → FFmpeg finalizes the current segment header
                self._proc.send_signal(signal.SIGINT)
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log.warning("pipeline.ffmpeg_timeout, sending SIGTERM")
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    log.error("pipeline.ffmpeg_kill")
                    self._proc.kill()
                    self._proc.wait()
            except OSError:  # pragma: no cover — process already exited
                pass

            self._last_returncode = self._proc.returncode
            self._proc = None
            log.info("pipeline.ffmpeg_exited", returncode=self._last_returncode)

        # Wait for stderr thread to finish
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=2)
            self._stderr_thread = None

        # Stop promoters (they do one final pass promoting ALL remaining files)
        for promoter in self._promoters:
            promoter.stop()
            promoter.join(timeout=3)

        promoted = self.segments_promoted

        # Emit final recording stats summary before clearing state
        if self._stats is not None:
            self._stats.emit_final_summary()  # pragma: no cover — integration-tested

        log.info(
            "pipeline.stopped",
            segments_promoted=promoted,
            stderr_errors=len(self.stderr_errors),
        )

        # Cache final counts before clearing promoter references
        self._final_promoted = promoted
        self._promoters = []
