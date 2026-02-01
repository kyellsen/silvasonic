import socket
import time

import pytest
from silvasonic.core.schemas.devices import MicrophoneProfile
from silvasonic.recorder.stream import FFmpegStreamer


@pytest.fixture
def integration_profile():
    """Create a profile for integration testing."""
    return MicrophoneProfile(
        schema_version="1.0",
        slug="integration_test",
        name="Integration Test",
        audio={"sample_rate": 48000, "channels": 1, "format": "S16LE"},
        stream={
            "raw_enabled": True,
            "processed_enabled": True,
            "live_stream_enabled": True,
        },
    )


@pytest.mark.integration
def test_end_to_end_recording(integration_profile, tmp_path):
    """Run the streamer with a synthetic sine wave input for 5 seconds."""
    import shutil
    import subprocess

    # Prerequisite Check
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not found via which")

    # Check for libmp3lame
    try:
        result = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True)
        if result.returncode != 0:
            pytest.skip(f"ffmpeg -encoders failed with code {result.returncode}")

        encoders = result.stdout
        if not encoders:
            # Fallback to stderr just in case
            encoders = result.stderr

        if "libmp3lame" not in encoders:
            pytest.skip("ffmpeg installed but missing libmp3lame encoder in output")

    except Exception as e:
        pytest.skip(f"Failed to check codecs: {e}")

    # Debug: Check basic functionality
    ret = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
    if ret.returncode != 0:
        pytest.fail(f"Basic ffmpeg -version failed: {ret.returncode}\n{ret.stderr}")

    print(f"ffmpeg version output: {ret.stdout[:200]}")

    # Use lavfi sine wave generator (infinite)
    streamer = FFmpegStreamer(
        integration_profile, tmp_path, input_format="lavfi", input_device="sine=frequency=1000"
    )

    streamer.start()

    # Wait for startup and recording
    time.sleep(5)

    assert streamer.running
    assert streamer.process.poll() is None

    # 1. Check Network Socket (Live Stream)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex(("127.0.0.1", 8000))
    sock.close()
    assert result == 0, "Port 8000 should be open"

    streamer.stop()

    # 2. Check Files
    raw_files = list((tmp_path / "raw").glob("*.wav"))
    proc_files = list((tmp_path / "processed").glob("*.wav"))

    assert len(raw_files) >= 1, "Raw files should be created"
    assert len(proc_files) >= 1, "Processed files should be created"

    # Optional: Check file sizes are > 0
    assert raw_files[0].stat().st_size > 0
    assert proc_files[0].stat().st_size > 0
