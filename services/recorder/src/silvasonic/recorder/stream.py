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
        segment_time_s: int = 60,
        input_format: str = "alsa",
        input_device: str | None = None,
    ) -> None:
        """Initialize the FFmpeg streamer."""
        self.profile = profile
        self.output_dir = output_dir
        self.alsa_index = alsa_card_index if alsa_card_index is not None else 0
        self.segment_time = segment_time_s
        self.input_format = input_format
        # Default to hw:X for alsa if not provided
        self.input_device = input_device if input_device is not None else f"hw:{self.alsa_index}"

        self.process: subprocess.Popen[str] | None = None
        self.running = False

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
        cmd = ffmpeg.merge_outputs(*outputs).global_args("-y").compile()
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
        """Reads stderr from FFmpeg to log errors."""
        while self.running and self.process and self.process.poll() is None:
            if self.process.stderr:
                line = self.process.stderr.readline()
                if line:
                    # FFmpeg logs a lot of stats, maybe filter only errors or periodic stats
                    if "Error" in line:
                        logger.error("ffmpeg_error", output=line.strip())
            time.sleep(0.1)

        if self.running:
            # Process died unexpectedly
            logger.critical(
                "ffmpeg_process_died", exit_code=self.process.returncode if self.process else -1
            )
            # In a real system, we'd trigger a restart or exit so the container restarts
            # sys.exit(1)
