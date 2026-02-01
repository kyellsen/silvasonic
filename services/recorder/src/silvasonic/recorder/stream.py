import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import ffmpeg
import structlog
from silvasonic.core.schemas.devices import MicrophoneProfile

logger = structlog.get_logger()


class FFmpegStreamer:
    """Manages a subprocess executing a complex FFmpeg filter graph.

    Splits input into multiple output streams (Raw, Processed, etc.).
    """

    def __init__(
        self,
        profile: MicrophoneProfile,
        output_dir: Path,
        alsa_card_index: int | None = None,
        input_format: str = "alsa",
        input_device: str | None = None,
        on_segment_complete: Any | None = None,
    ) -> None:
        """Initialize the FFmpeg streamer."""
        self.profile = profile
        self.output_dir = output_dir
        self.alsa_index = alsa_card_index if alsa_card_index is not None else 0
        self.input_format = input_format
        # Default to hw:X for alsa if not provided
        self.input_device = input_device if input_device is not None else f"hw:{self.alsa_index}"
        self.on_segment_complete = on_segment_complete

        self.process: subprocess.Popen[str] | None = None
        self.running = False
        self.watchdog_thread: threading.Thread | None = None

    def build_command(self) -> list[str]:
        """Construct the FFmpeg command arguments."""
        # Inputs
        input_args: dict[str, Any] = {}

        # Only add audio params if using ALSA (lavfi generates its own props)
        if self.input_format == "alsa":
            input_args.update(
                {
                    "ac": self.profile.audio.channels,
                    "ar": self.profile.audio.sample_rate,
                    "thread_queue_size": 1024,
                }
            )

        input_args["f"] = self.input_format

        stream = ffmpeg.input(self.input_device, **input_args)

        # Filters: Determine which outputs are enabled
        needs_raw = self.profile.stream.raw_enabled
        needs_processed = self.profile.stream.processed_enabled
        needs_live = self.profile.stream.live_stream_enabled

        output_count = sum([needs_raw, needs_processed, needs_live])

        if output_count == 0:
            raise ValueError("No output streams enabled in profile!")

        # Create split streams if multiple outputs
        streams = []
        if output_count > 1:
            split_streams = stream.filter_multi_output("asplit", output_count)
            # split_streams is a list of stream nodes, but filter_multi_output returns non-iterable implementation sometimes?
            # ffmpeg-python: .filter_multi_output returns a wrapper that can be indexed.
            for i in range(output_count):
                streams.append(split_streams[i])
        else:
            streams.append(stream)

        # Assign streams to consumers
        # Order: Raw -> Processed -> Live (arbitrary, just need to consume list)
        outputs = []

        stream_idx = 0

        # Stream 1: Raw (Native)
        if needs_raw:
            s_raw = streams[stream_idx]
            stream_idx += 1

            # Format: /data/recordings/{mic}/raw/%Y-%m-%d_%H-%M-%S.wav
            raw_path = str(self.output_dir / "raw" / "%Y-%m-%d_%H-%M-%S.wav")
            out_raw = s_raw.output(
                raw_path,
                f="segment",
                segment_time=self.profile.stream.segment_duration_s,
                segment_format="wav",
                strftime=1,
                acodec="pcm_s24le",  # Store High Res as 24-bit
                reset_timestamps=1,
            )
            outputs.append(out_raw)

        # Stream 2: Processed (48kHz)
        if needs_processed:
            s_proc = streams[stream_idx]
            stream_idx += 1

            proc_path = str(self.output_dir / "processed" / "%Y-%m-%d_%H-%M-%S.wav")

            # Apply Gain?
            if self.profile.processing.gain_db != 0.0:
                s_proc = s_proc.filter("volume", volume=f"{self.profile.processing.gain_db}dB")

            out_proc = s_proc.filter("aresample", 48000).output(
                proc_path,
                f="segment",
                segment_time=self.profile.stream.segment_duration_s,
                segment_format="wav",
                strftime=1,
                acodec="pcm_s16le",  # Store Standard as 16-bit
                reset_timestamps=1,
            )
            outputs.append(out_proc)

        # Stream 3: Live MP3
        if needs_live:
            s_live = streams[stream_idx]
            stream_idx += 1

            # tcp://0.0.0.0:8000?listen=1
            live_port = 8000
            live_url = f"tcp://0.0.0.0:{live_port}?listen=1"

            if self.profile.processing.gain_db != 0.0:
                s_live = s_live.filter("volume", volume=f"{self.profile.processing.gain_db}dB")

            out_live = s_live.filter("aresample", 48000).output(
                live_url,
                format="mp3",
                acodec="libmp3lame",
                audio_bitrate="128k",
                content_type="audio/mpeg",
                flush_packets=1,
            )
            outputs.append(out_live)

        # Combine
        # Add -y to force overwrite (prevent stuck on prompts)
        cmd = ffmpeg.merge_outputs(*outputs).global_args("-y", "-loglevel", "info").compile()
        return list(cmd)

    def start(self) -> None:
        """Start the FFmpeg subprocess."""
        cmd = self.build_command()
        cmd_str = " ".join(cmd)
        logger.info("starting_ffmpeg", command=cmd_str)

        self.running = True

        # Checks if outputs exist
        (self.output_dir / "raw").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "processed").mkdir(parents=True, exist_ok=True)

        self.process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
        )

        # Watchdog Thread
        self.watchdog_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.watchdog_thread.start()

    def stop(self) -> None:
        """Stop the subprocess gracefully."""
        self.running = False
        if self.process:
            logger.info("stopping_ffmpeg")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def _monitor_loop(self) -> None:
        """Reads stderr from FFmpeg to log errors and detect segment completion."""
        # Detect: [segment @ 0x...] segment '...' starts
        # This implies previous segment finished.

        last_segment_file: str | None = None
        last_segment_start_time = time.time()

        while self.running and self.process and self.process.poll() is None:
            if self.process.stderr:
                line = self.process.stderr.readline()
                if line:
                    line_s = line.strip()

                    # 1. Error Logging
                    if "error" in line_s.lower():
                        logger.error("ffmpeg_error", output=line_s)

                    # 2. Segment Detection
                    # Pattern 1: [segment @ ...] segment '/path/to/file.wav' starts
                    # Pattern 2: [segment @ ...] Opening '/path/to/file.wav' for writing
                    is_p1 = "segment" in line_s and "starts" in line_s and "'" in line_s
                    is_p2 = (
                        "segment" in line_s
                        and "Opening" in line_s
                        and "for writing" in line_s
                        and "'" in line_s
                    )

                    if is_p1 or is_p2:
                        try:
                            # Parse filename
                            # Split by ' and take 2nd item (index 1)
                            parts = line_s.split("'")
                            if len(parts) >= 2:
                                current_file = parts[1]
                                now = time.time()

                                # If we had a previous file, it is now finished
                                if (
                                    last_segment_file
                                    and last_segment_file != current_file
                                    and self.on_segment_complete
                                ):
                                    # Rough duration calculation
                                    duration = now - last_segment_start_time

                                    # Trigger callback
                                    try:
                                        self.on_segment_complete(last_segment_file, duration)
                                    except Exception as e:
                                        logger.error("callback_failed", error=str(e))

                                if last_segment_file != current_file:
                                    last_segment_file = current_file
                                    last_segment_start_time = now
                        except Exception as e:
                            logger.error("segment_parse_failed", error=str(e), line=line_s)

            # Avoid tight loop if no output, but readline blocks so sleep might not be needed if not using non-blocking IO.
            # Popen default is blocking read, so we are good.
            # But if readline returns empty string (EOF) we break, handled by loop condition?
            # Actually readline returns '' on EOF.
            if not line:
                # EOF or no data yet? If process is running, it might just be quiet.
                # But universal_newlines=True makes it text mode.
                time.sleep(0.1)

        if self.running:
            # Process died unexpectedly
            logger.critical(
                "ffmpeg_process_died", exit_code=self.process.returncode if self.process else -1
            )
