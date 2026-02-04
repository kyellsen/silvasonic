from unittest.mock import Mock

import pytest
from silvasonic.core.schemas.devices import MicrophoneProfile
from silvasonic.recorder.stream import FFmpegStreamer


@pytest.fixture
def unit_profile():
    """Create a mock microphone profile for unit tests."""
    return MicrophoneProfile(
        schema_version="1.0",
        slug="unit_test",
        name="Unit Test",
        audio={"sample_rate": 48000, "channels": 1, "format": "S16LE"},
        stream={
            "raw_enabled": True,
            "processed_enabled": False,
            "live_stream_enabled": True,
            "segment_duration_s": 15,
        },
    )


@pytest.fixture(autouse=True)
def mock_logger(mocker):
    """Mock the module-level logger to suppress output."""
    return mocker.patch("silvasonic.recorder.stream.logger")


def test_monitor_loop_segment_detection(unit_profile, tmp_path, mocker):
    """Test that segment completion lines trigger the callback."""
    # Mock callback
    mock_callback = Mock()
    streamer = FFmpegStreamer(
        unit_profile, tmp_path, "tcp://localhost:8000", on_segment_complete=mock_callback
    )
    streamer.running = True

    # Mock process and stderr
    mock_process = mocker.Mock()
    streamer.process = mock_process
    mock_process.poll.return_value = None  # Process alive

    # Simulate stderr output
    # We yield lines then stop the loop by setting running=False
    stderr_lines = [
        "[segment] Opening 'raw/2023-01-01_12-00-00.wav' for writing",  # First file
        "misc output",
        "[segment] Opening 'raw/2023-01-01_12-00-15.wav' for writing",  # Second file -> First one complete
    ]

    def side_effect_readline():
        if stderr_lines:
            return stderr_lines.pop(0)
        streamer.running = False  # Stop loop
        return ""

    mock_process.stderr.readline.side_effect = side_effect_readline

    # Mock time.time to calculate duration
    mocker.patch("time.time", side_effect=[1000.0, 1015.0, 1030.0])  # Start 1, Start 2 (Diff 15s)

    streamer._monitor_loop()

    # Verify callback called for the first file
    mock_callback.assert_called_with("raw/2023-01-01_12-00-00.wav", 15.0)


def test_callback_failure_does_not_crash_loop(unit_profile, tmp_path, mocker):
    """Test that if the callback raises, the loop continues."""
    mock_callback = Mock(side_effect=Exception("Boom"))
    streamer = FFmpegStreamer(
        unit_profile, tmp_path, "tcp://localhost:8000", on_segment_complete=mock_callback
    )
    streamer.running = True
    mock_process = mocker.Mock()
    streamer.process = mock_process
    mock_process.poll.return_value = None

    stderr_lines = [
        "[segment] Opening 'raw/file1.wav' for writing",
        "[segment] Opening 'raw/file2.wav' for writing",  # Trigger callback
    ]

    def side_effect_readline():
        if stderr_lines:
            return stderr_lines.pop(0)
        streamer.running = False
        return ""

    mock_process.stderr.readline.side_effect = side_effect_readline

    # Should not raise
    streamer._monitor_loop()
    mock_callback.assert_called_once()


def test_icecast_failure_trigger_degraded_mode(unit_profile, tmp_path, mocker):
    """Test entering degraded mode on Icecast failure."""
    streamer = FFmpegStreamer(unit_profile, tmp_path, "tcp://localhost:8000")
    streamer.process = mocker.Mock()
    streamer.process.returncode = 1

    # Mock recovery thread start
    mock_thread = mocker.patch("threading.Thread")

    errors = ["Error opening output tcp://localhost:8000: Connection refused"]
    streamer._handle_crash(errors)

    assert streamer.degraded_mode is True
    # Should start recovery thread
    mock_thread.assert_called_once()


def test_recovery_loop_restores_normal_mode(unit_profile, tmp_path, mocker):
    """Test that successful connection restores normal mode."""
    streamer = FFmpegStreamer(unit_profile, tmp_path, "tcp://localhost:8000")
    streamer.running = True
    streamer.degraded_mode = True
    streamer.process = mocker.Mock()  # Fake existing process

    # Mock socket connection success
    mocker.patch("socket.create_connection")

    streamer._recovery_loop()

    assert streamer.degraded_mode is False
    streamer.process.terminate.assert_called_once()


def test_recovery_loop_retries_on_fail(unit_profile, tmp_path, mocker):
    """Test that recovery loop retries if connection fails."""
    streamer = FFmpegStreamer(unit_profile, tmp_path, "tcp://localhost:8000")
    streamer.running = True
    streamer.degraded_mode = True

    # Mock socket connection to fail once then succeed
    mock_socket = mocker.patch("socket.create_connection")
    mock_socket.side_effect = [ConnectionRefusedError, mocker.MagicMock()]

    # Mock sleep to avoid waiting
    mocker.patch("time.sleep")

    streamer._recovery_loop()

    assert mock_socket.call_count == 2
    assert streamer.degraded_mode is False


def test_recovery_loop_url_parse_error(unit_profile, tmp_path, mocker):
    """Test recovery loop exits on invalid URL."""
    streamer = FFmpegStreamer(unit_profile, tmp_path, "invalid_url")
    streamer._recovery_loop()
    # just shouldn't crash


def test_degraded_mode_forces_raw_output(unit_profile, tmp_path):
    """Test that degraded mode forces raw output if nothing else enabled."""
    # Setup profile with ONLY live stream enabled
    unit_profile.stream.raw_enabled = False
    unit_profile.stream.processed_enabled = False
    unit_profile.stream.live_stream_enabled = True

    streamer = FFmpegStreamer(unit_profile, tmp_path, "tcp://localhost:8000")
    streamer.degraded_mode = True

    cmd = streamer.build_command()
    cmd_str = str(cmd)

    # Should have raw output enabled
    assert "wav" in cmd_str
    assert "segment" in cmd_str
    # Should NOT have live output
    assert "tcp://" not in cmd_str


def test_start_idempotency(unit_profile, tmp_path, mocker):
    """Test that start() does nothing if already running."""
    streamer = FFmpegStreamer(unit_profile, tmp_path, "tcp://localhost:8000")
    streamer.process = mocker.Mock()
    streamer.process.poll.return_value = None  # Running

    streamer.start()

    # Should not create new process (we didn't mock Popen here, so if it did, it would fail or use real Popen)
    # Just verify no side effects essentially
    assert streamer.running is False  # Default init
    # Wait, start sets running=True. But if we return early, it stays what it was?
    # Actually if process is set manually, running might not look at that.
    # The code checks `if self.process and self.process.poll() is None: return`


def test_handle_crash_generic(unit_profile, tmp_path, mocker):
    """Test generic crash doesn't trigger degraded mode."""
    streamer = FFmpegStreamer(unit_profile, tmp_path, "tcp://localhost:8000")
    streamer.process = mocker.Mock()
    streamer.process.returncode = 139  # Segfault

    errors = ["Segmentation fault"]
    streamer._handle_crash(errors)

    assert streamer.degraded_mode is False


def test_handle_crash_already_degraded(unit_profile, tmp_path, mocker):
    """Test crash while already degraded logs warning but stays degraded."""
    streamer = FFmpegStreamer(unit_profile, tmp_path, "tcp://localhost:8000")
    streamer.degraded_mode = True
    streamer.process = mocker.Mock()
    streamer.process.returncode = 1

    streamer._handle_crash(["some error"])
    assert streamer.degraded_mode is True


def test_monitor_loop_restarts_process(unit_profile, tmp_path, mocker):
    """Test that monitor loop restarts process on crash."""
    streamer = FFmpegStreamer(unit_profile, tmp_path, "tcp://localhost:8000")
    streamer.running = True

    mock_process = mocker.Mock()
    streamer.process = mock_process

    # 1. poll() returns not None (dead)
    # 2. poll() returns None (alive after restart) - but wait, handle_crash called.
    # Logic:
    #   if dead:
    #       handle_crash()
    #       sleep()
    #       if running and (no process or dead): start()

    mock_process.poll.return_value = 1

    # Mock handle_crash and start
    mocker.patch.object(streamer, "_handle_crash")
    mock_start = mocker.patch.object(streamer, "start")

    # To break the loop
    def side_effect_sleep(dur):
        if dur == 2.0:  # The restart sleep
            pass
        if dur == 0.1:  # The loop sleep
            streamer.running = False

    mocker.patch("time.sleep", side_effect=side_effect_sleep)

    # We need to ensure start() is called.

    # We need to break the loop somehow.
    # Let's use side_effect on handle_crash to decrement a counter or something?
    # Or just let it run once.

    # Alternative: call _monitor_loop in thread? No.
    # Let's just mock start() to set running=False to break loop? No start sets running=True.

    # Let's make sleep raise an exception to break the loop after verified call
    class BreakLoopError(Exception):
        pass

    mocker.patch("time.sleep", side_effect=[None, BreakLoopError])  # Sleep 2.0 then Break

    try:
        streamer._monitor_loop()
    except BreakLoopError:
        pass

    mock_start.assert_called_once()


def test_monitor_read_error_handled(unit_profile, tmp_path, mocker):
    """Test that exceptions during readline are swallowed."""
    streamer = FFmpegStreamer(unit_profile, tmp_path, "tcp://localhost:8000")
    streamer.running = True
    streamer.process = mocker.Mock()
    streamer.process.poll.return_value = None
    streamer.process.stderr.readline.side_effect = ValueError("Read error")

    mocker.patch("time.sleep", side_effect=lambda x: setattr(streamer, "running", False))

    # Should not raise
    streamer._monitor_loop()


def test_monitor_segment_parse_error(unit_profile, tmp_path, mocker):
    """Test that malformed segment lines log error but don't crash."""
    streamer = FFmpegStreamer(unit_profile, tmp_path, "tcp://localhost:8000")
    streamer.running = True
    streamer.process = mocker.Mock()
    streamer.process.poll.return_value = None

    # Explicitly yield the bad line, then empty string (EOF) to trigger sleep -> stop
    streamer.process.stderr.readline.side_effect = [
        "segment 'malformed checking",
        "",  # End of stream (EOF)
    ]

    # When sleep is called (due to empty line), stop the loop
    mocker.patch("time.sleep", side_effect=lambda x: setattr(streamer, "running", False))

    streamer._monitor_loop()

    # If we reached here, it didn't hang.
    # Verify readline was called (at least once)
    assert streamer.process.stderr.readline.call_count >= 1
