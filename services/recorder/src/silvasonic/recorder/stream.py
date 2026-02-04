import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import ffmpeg
import structlog
from silvasonic.core.schemas.devices import MicrophoneProfile

logger = structlog.get_logger()


class FFmpegStreamer:
    """Manages a subprocess executing a complex FFmpeg filter graph.

    Robustness Features:
    - Degraded Mode: If Icecast fails, restarts in file-only mode.
    - Auto-Recovery: Background thread checks Icecast availability to restore live stream.
    - Process Supervision: Automatically restarts on crash.
    """

    def __init__(
        self,
        profile: MicrophoneProfile,
        output_dir: Path,
        live_stream_url: str,
        alsa_card_index: int | None = None,
        input_format: str = "alsa",
        input_device: str | None = None,
        on_segment_complete: Any | None = None,
    ) -> None:
        """Initialize the FFmpeg streamer."""
        self.profile = profile
        self.output_dir = output_dir
        self.live_stream_url = live_stream_url
        self.alsa_index = alsa_card_index if alsa_card_index is not None else 0
        self.input_format = input_format
        self.input_device = (
            input_device if input_device is not None else f"plughw:{self.alsa_index}"
        )
        self.on_segment_complete = on_segment_complete

        self.process: subprocess.Popen[str] | None = None
        self.running = False
        self.watchdog_thread: threading.Thread | None = None
        self.recovery_thread: threading.Thread | None = None

        # State
        self.degraded_mode = False  # True = No Streaming (Icecast Down)
        self.last_icecast_error_check = 0.0

    def build_command(self) -> list[str]:
        """Construct the FFmpeg command arguments."""
        input_args: dict[str, Any] = {}

        if self.input_format == "alsa":
            input_args.update(
                {
                    "ac": self.profile.audio.channels,
                    "ar": self.profile.audio.sample_rate,
                    "thread_queue_size": 1024,
                }
            )

        input_args["f"] = self.input_format

        if self.input_format == "lavfi":
            # crucial: read at native frame rate to avoid infinite loop / resource exhaustion
            input_args["re"] = None

        stream = ffmpeg.input(self.input_device, **input_args)

        needs_raw = self.profile.stream.raw_enabled
        needs_processed = self.profile.stream.processed_enabled
        # Degraded Mode: Force live_stream to False if Icecast is down
        needs_live = self.profile.stream.live_stream_enabled and not self.degraded_mode

        output_count = sum([needs_raw, needs_processed, needs_live])

        if output_count == 0:
            # Fallback if everything is disabled (scan-only mode concept?)
            # But for recorder service this shouldn't happen unless config is broken.
            # We can just record dummy or raise.
            # If degraded mode kills the only output, we force raw?
            if self.degraded_mode and self.profile.stream.live_stream_enabled:
                logger.warning("degraded_mode_no_outputs_forcing_raw")
                needs_raw = True
                output_count = 1
            else:
                raise ValueError("No output streams enabled in profile!")

        streams = []
        if output_count > 1:
            split_streams = stream.filter_multi_output("asplit", output_count)
            for i in range(output_count):
                streams.append(split_streams[i])
        else:
            streams.append(stream)

        outputs = []
        stream_idx = 0

        # Stream 1: Raw
        if needs_raw:
            s_raw = streams[stream_idx]
            stream_idx += 1
            raw_path = str(self.output_dir / "raw" / "%Y-%m-%d_%H-%M-%S.wav")
            out_raw = s_raw.output(
                raw_path,
                f="segment",
                segment_time=self.profile.stream.segment_duration_s,
                segment_format="wav",
                strftime=1,
                acodec="pcm_s24le",
                reset_timestamps=1,
            )
            outputs.append(out_raw)

        # Stream 2: Processed
        if needs_processed:
            s_proc = streams[stream_idx]
            stream_idx += 1
            proc_path = str(self.output_dir / "processed" / "%Y-%m-%d_%H-%M-%S.wav")
            if self.profile.processing.gain_db != 0.0:
                s_proc = s_proc.filter("volume", volume=f"{self.profile.processing.gain_db}dB")

            out_proc = s_proc.filter("aresample", 48000).output(
                proc_path,
                f="segment",
                segment_time=self.profile.stream.segment_duration_s,
                segment_format="wav",
                strftime=1,
                acodec="pcm_s16le",
                reset_timestamps=1,
            )
            outputs.append(out_proc)

        # Stream 3: Live
        if needs_live:
            s_live = streams[stream_idx]
            stream_idx += 1
            if self.profile.processing.gain_db != 0.0:
                s_live = s_live.filter("volume", volume=f"{self.profile.processing.gain_db}dB")

            out_live = s_live.filter("aresample", 48000).output(
                self.live_stream_url,
                format="ogg",
                acodec="libopus",
                audio_bitrate="64k",
                content_type="application/ogg",
                ice_name=f"Silvasonic Live - {self.profile.name}",
                ice_description="Real-time biological monitoring stream (Opus)",
            )
            outputs.append(out_live)

        cmd = ffmpeg.merge_outputs(*outputs).global_args("-y", "-loglevel", "info").compile()
        return list(cmd)

    def start(self) -> None:
        """Start the FFmpeg subprocess."""
        if self.process and self.process.poll() is None:
            logger.warning("ffmpeg_already_running")
            return

        cmd = self.build_command()
        cmd_str = " ".join(cmd)

        mode = "DEGRADED (Files Only)" if self.degraded_mode else "NORMAL (Live + Files)"
        logger.info("starting_ffmpeg", command=cmd_str, mode=mode)

        self.running = True

        (self.output_dir / "raw").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "processed").mkdir(parents=True, exist_ok=True)

        self.process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
        )

        # Watchdog Thread
        if not self.watchdog_thread or not self.watchdog_thread.is_alive():
            self.watchdog_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.watchdog_thread.start()

    def stop(self) -> None:
        """Stop the subprocess gracefully."""
        self.running = False

        # Stop recovery thread if active
        # We don't join explicitly to avoid blocking, but the loop checks self.running

        if self.process:
            logger.info("stopping_ffmpeg")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def _monitor_loop(self) -> None:
        """Reads stderr from FFmpeg to log errors and supervise process."""
        stream_states: dict[str, dict[str, Any]] = {}
        recent_errors: list[str] = []

        while self.running:
            if not self.process:
                time.sleep(0.1)
                continue

            # Check if dead
            if self.process.poll() is not None:
                self._handle_crash(recent_errors)
                # If handle_crash restarts, we loop back.
                # If catastrophic failure/shutdown, self.running becomes False.
                # Allow a small cool-down to prevent tight loop if restart fails instantly
                time.sleep(2.0)
                # Restart if still meant to be running
                if self.running and (not self.process or self.process.poll() is not None):
                    logger.info("watchdog_restarting_ffmpeg")
                    self.start()
                continue

            # Read Output
            line = ""
            try:
                if self.process.stderr:
                    line = self.process.stderr.readline()
            except Exception:
                pass

            if not line:
                # No output, just wait
                time.sleep(0.1)
                continue

            line_s = line.strip()

            # Keep recent errors for context on crash
            if "error" in line_s.lower() or "fail" in line_s.lower():
                recent_errors.append(line_s)
                if len(recent_errors) > 10:
                    recent_errors.pop(0)

            # 1. Error Logging (Real-time)
            if "error" in line_s.lower():
                logger.error("ffmpeg_error", output=line_s)

            # 2. Segment Detection
            if "segment" in line_s and "'" in line_s:
                # Pattern: segment 'file' starts
                if "starts" in line_s or ("Opening" in line_s and "for writing" in line_s):
                    try:
                        parts = line_s.split("'")
                        if len(parts) >= 2:
                            current_file = parts[1]
                            now = time.time()

                            # Identify stream lane by parent directory (e.g. .../raw/ vs .../processed/)
                            parent_dir = str(Path(current_file).parent)

                            if parent_dir not in stream_states:
                                # Initialize state for new stream lane
                                stream_states[parent_dir] = {
                                    "last_file": current_file,
                                    "start_time": now,
                                }
                            else:
                                state = stream_states[parent_dir]
                                last_file = state["last_file"]
                                start_time = state["start_time"]

                                if last_file != current_file:
                                    # Previous segment finished in this lane
                                    if self.on_segment_complete:
                                        duration = now - start_time
                                        try:
                                            self.on_segment_complete(last_file, duration)
                                        except Exception as e:
                                            logger.error("callback_failed", error=str(e))

                                    # Update state for this lane
                                    state["last_file"] = current_file
                                    state["start_time"] = now
                    except Exception as e:
                        logger.error("segment_parse_failed", error=str(e), line=line_s)

    def _handle_crash(self, errors: list[str]) -> None:
        """Analyze crash and decide on Degraded Mode."""
        assert self.process is not None
        logger.warning("ffmpeg_process_died_unexpectedly", exit_code=self.process.returncode)

        payload = " ".join(errors).lower()
        icecast_issues = ["connection refused", "input/output error", "icecast", "server not found"]

        is_icecast_fail = any(x in payload for x in icecast_issues)

        if is_icecast_fail and not self.degraded_mode:
            logger.warning("detected_icecast_failure_entering_degraded_mode")
            self.degraded_mode = True

            # Start Recovery Thread
            if not self.recovery_thread or not self.recovery_thread.is_alive():
                self.recovery_thread = threading.Thread(target=self._recovery_loop, daemon=True)
                self.recovery_thread.start()

        elif self.degraded_mode:
            logger.warning("crash_in_degraded_mode_retrying")
        else:
            logger.error("generic_crash_retrying")

    def _recovery_loop(self) -> None:
        """Background thread to check for Icecast availability."""
        logger.info("recovery_thread_started")

        # Parse Host/Port
        try:
            parsed = urlparse(self.live_stream_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 8000
        except Exception as e:
            logger.error("recovery_failed_url_parse", error=str(e))
            return

        backoff = 5.0

        while self.running and self.degraded_mode:
            try:
                # Try TCP detection
                with socket.create_connection((host, port), timeout=3.0):
                    logger.info("icecast_recovered_restoring_functionality")
                    self.degraded_mode = False
                    # Stop current FFmpeg (Files Only)
                    if self.process:
                        self.process.terminate()
                        # Watchdog will see it died and restart it.
                        # Since degraded_mode is False, it will restart with Live Mode.
                    return
            except Exception:
                logger.debug("icecast_still_unreachable", retry_in=backoff)

            time.sleep(backoff)
            backoff = min(60.0, backoff * 1.5)
