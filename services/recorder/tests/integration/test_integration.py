import contextlib
import socket
import threading
import time

import pytest
from silvasonic.core.schemas.devices import MicrophoneProfile
from silvasonic.recorder.stream import FFmpegStreamer


class MockIcecastServer:
    """A minimal mock Icecast server that accepts connections and discards data."""

    def __init__(self, port=8000):
        """Initialize the mock server."""
        self.port = port
        self.running = False
        self.thread = None
        self.sock = None

    def start(self):
        """Start the mock server in a separate thread."""
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", self.port))
        self.sock.listen(1)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the mock server and close the socket."""
        self.running = False
        if self.sock:
            self.sock.close()
        if self.thread:
            self.thread.join(timeout=1)

    def _run(self):
        try:
            while self.running:
                try:
                    conn, _ = self.sock.accept()
                except OSError:
                    break

                with conn:
                    # Read headers (simplified)
                    conn.settimeout(1.0)
                    try:
                        while True:
                            data = conn.recv(1024)
                            if b"\r\n\r\n" in data or not data:
                                break
                    except TimeoutError:
                        pass

                    # Send OK response to satisfy FFmpeg icecast protocol
                    try:
                        conn.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
                    except OSError:
                        pass

                    # Discard stream data
                    try:
                        while self.running:
                            if not conn.recv(4096):
                                break
                    except OSError:
                        pass
        except Exception:
            pass


@contextlib.contextmanager
def mock_icecast_server(port=8000):
    """Context manager to start and stop the MockIcecastServer."""
    server = MockIcecastServer(port)
    server.start()
    try:
        yield server
    finally:
        server.stop()


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
    # Find a free port dynamically to avoid collisions
    sock = socket.socket()
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()

    with mock_icecast_server(port=port):
        streamer = FFmpegStreamer(
            integration_profile,
            tmp_path,
            live_stream_url=f"icecast://source:hackme@localhost:{port}/live",
            input_format="lavfi",
            input_device="sine=frequency=1000",
        )

        streamer.start()

        # Wait for startup and recording
        time.sleep(5)

        assert streamer.running
        assert streamer.process.poll() is None

        # 1. Check Network Socket (Live Stream)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        assert result == 0, f"Port {port} should be open"

        streamer.stop()

    # 2. Check Files
    raw_files = list((tmp_path / "raw").glob("*.wav"))
    proc_files = list((tmp_path / "processed").glob("*.wav"))

    assert len(raw_files) >= 1, "Raw files should be created"
    assert len(proc_files) >= 1, "Processed files should be created"

    # Optional: Check file sizes are > 0
    assert raw_files[0].stat().st_size > 0
    assert proc_files[0].stat().st_size > 0
