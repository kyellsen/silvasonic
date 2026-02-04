import subprocess

import pytest
from silvasonic.core.schemas.devices import MicrophoneProfile
from silvasonic.recorder.stream import FFmpegStreamer


@pytest.fixture
def basic_profile():
    """Create a basic microphone profile for testing."""
    return MicrophoneProfile(
        schema_version="1.0",
        slug="test",
        name="Test",
        audio={"sample_rate": 48000, "channels": 1, "format": "S16LE"},
        stream={"raw_enabled": True, "processed_enabled": False},
    )


def test_raw_only_command(basic_profile, tmp_path):
    """Test that the command builder handles raw-only profiles correctly."""
    streamer = FFmpegStreamer(
        basic_profile,
        tmp_path,
        live_stream_url="icecast://source:hackme@silvasonic-icecast:8000/live/test.opus",
    )
    cmd = streamer.build_command()
    # verify cmd list structure
    # inputs
    assert "-f" in cmd
    assert "alsa" in cmd
    assert "hw:0" in cmd[cmd.index("-i") + 1]

    # outputs
    assert "raw" in str(cmd)
    assert "processed" not in str(cmd)


def test_dual_stream_command(basic_profile, tmp_path):
    """Test that the command builder handles dual stream profiles correctly."""
    basic_profile.stream.processed_enabled = True
    streamer = FFmpegStreamer(
        basic_profile,
        tmp_path,
        live_stream_url="icecast://source:hackme@silvasonic-icecast:8000/live/test.opus",
    )
    cmd = streamer.build_command()

    # Check for split filter
    assert "split" in str(cmd) or "filter_complex" in str(cmd) or "-filter_complex" in cmd

    # outputs
    assert "raw" in str(cmd)
    assert "processed" in str(cmd)


def test_live_stream_command_enabled(basic_profile, tmp_path):
    """Test that the command builder handles live stream profiles correctly."""
    basic_profile.stream.live_stream_enabled = True
    streamer = FFmpegStreamer(
        basic_profile,
        tmp_path,
        live_stream_url="icecast://source:hackme@silvasonic-icecast:8000/live/test.opus",
    )
    cmd = streamer.build_command()
    cmd_str = str(cmd)

    # Check for Icecast output
    assert "icecast://" in cmd_str
    assert "ice_name" in cmd_str
    assert "content_type" in cmd_str


def test_stream_lifecycle(basic_profile, tmp_path, mocker):
    """Test start, stop and monitor loop using mocks."""
    streamer = FFmpegStreamer(
        basic_profile,
        tmp_path,
        live_stream_url="icecast://source:hackme@silvasonic-icecast:8000/live/test.opus",
    )

    # Mock subprocess.Popen
    mock_popen = mocker.patch("subprocess.Popen")
    mock_process = mock_popen.return_value
    mock_process.poll.side_effect = [None, None, -1] + [None] * 100  # Run loop twice then exit
    # Infinite empty strings after initial lines to prevent StopIteration
    mock_process.stderr.readline.side_effect = [
        "frame=  100 fps=0.0 q=-0.0 size=    1024kB time=00:00:10.00 bitrate= 838.9kbits/s speed=  20x",
        "Error: something went wrong",
        "",
    ] + [""] * 100
    mock_process.returncode = 1

    # Mock threading to avoid race conditions or actual threads
    # We will just call _monitor_loop manually for coverage,
    # but let verify start() spawns it.
    mock_thread = mocker.patch("threading.Thread")

    # Patch time.sleep to control the loop
    mock_sleep = mocker.patch("silvasonic.recorder.stream.time.sleep")

    def break_loop(*args):
        # When sleep(2.0) is called (after handle_crash), we break the loop
        if args and args[0] == 2.0:
            streamer.running = False

    mock_sleep.side_effect = break_loop

    # Test Start
    streamer.start()
    assert streamer.running
    mock_popen.assert_called_once()
    mock_thread.assert_called_once()

    # Manually invoke monitor loop to cover it
    # We need to simulate the thread target behavior
    # But since we mocked Thread, it didn't run.
    # Let's run the internal method directly for coverage.
    streamer.process = mock_process  # Ensure process is set (start does this)

    # Run the loop - it should exit when sleep(2.0) is called
    streamer._monitor_loop()

    # Test Stop
    streamer.stop()
    assert not streamer.running
    mock_process.terminate.assert_called_once()
    mock_process.wait.assert_called_once()


def test_stop_force_kill(basic_profile, tmp_path, mocker):
    """Test force kill on timeout."""
    streamer = FFmpegStreamer(
        basic_profile,
        tmp_path,
        live_stream_url="icecast://source:hackme@silvasonic-icecast:8000/live/test.opus",
    )
    streamer.process = mocker.Mock()
    streamer.process.wait.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=5)

    mock_proc = streamer.process
    streamer.stop()
    mock_proc.kill.assert_called_once()


def test_gain_application(basic_profile, tmp_path):
    """Test that volume filter is added when gain is non-zero."""
    # Test that volume filter is added when gain is non-zero
    basic_profile.processing.gain_db = 6.0
    basic_profile.stream.live_stream_enabled = True
    basic_profile.stream.processed_enabled = True  # Hit line 73
    streamer = FFmpegStreamer(
        basic_profile,
        tmp_path,
        live_stream_url="icecast://source:hackme@silvasonic-icecast:8000/live/test.opus",
    )
    cmd = streamer.build_command()
    cmd_str = str(cmd)

    assert "volume=6.0dB" in cmd_str


def test_no_outputs_error(basic_profile, tmp_path):
    """Test that building a command with no outputs raises an error."""
    # Disable all outputs
    basic_profile.stream.raw_enabled = False
    basic_profile.stream.processed_enabled = False
    basic_profile.stream.live_stream_enabled = False

    streamer = FFmpegStreamer(
        basic_profile,
        tmp_path,
        live_stream_url="icecast://source:hackme@silvasonic-icecast:8000/live/test.opus",
    )
    with pytest.raises(ValueError, match="No output streams"):
        streamer.build_command()
