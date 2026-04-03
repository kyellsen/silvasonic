"""Unit tests for the FLAC encoder."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from silvasonic.processor.modules.flac_encoder import FlacEncodingError, encode_wav_to_flac


@pytest.fixture
def dummy_wav(tmp_path: Path) -> Path:
    p = tmp_path / "test.wav"
    p.write_bytes(b"dummy wav data")
    return p


@pytest.mark.unit
async def test_encode_creates_flac_file(dummy_wav: Path) -> None:
    """Test successful ffmpeg execution."""

    async def mock_exec(*args: Any, **kwargs: Any) -> AsyncMock:
        out_path = Path(args[-1])
        out_path.write_bytes(b"dummy flac data")

        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate.return_value = (b"", b"")
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        result = await encode_wav_to_flac(dummy_wav, dummy_wav.parent)

    assert result.name == "test.flac"
    assert result.exists()
    assert result.read_bytes() == b"dummy flac data"


@pytest.mark.unit
async def test_encode_fails_on_ffmpeg_error(dummy_wav: Path) -> None:
    """Test handling of ffmpeg non-zero exit code."""

    async def mock_exec(*args: Any, **kwargs: Any) -> AsyncMock:
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate.return_value = (b"", b"ffmpeg error message")
        return proc

    with (
        patch("asyncio.create_subprocess_exec", side_effect=mock_exec),
        pytest.raises(FlacEncodingError, match="ffmpeg error message"),
    ):
        await encode_wav_to_flac(dummy_wav, dummy_wav.parent)


@pytest.mark.unit
async def test_encode_cleanup_on_failure(dummy_wav: Path) -> None:
    """Ensure partial FLAC files are removed on error."""

    async def mock_exec(*args: Any, **kwargs: Any) -> AsyncMock:
        out_path = Path(args[-1])
        out_path.write_bytes(b"partial flac data")

        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate.return_value = (b"", b"crash")
        return proc

    target_flac = dummy_wav.with_suffix(".flac")

    with (
        patch("asyncio.create_subprocess_exec", side_effect=mock_exec),
        pytest.raises(FlacEncodingError),
    ):
        await encode_wav_to_flac(dummy_wav, dummy_wav.parent)

    assert not target_flac.exists()


# ────────────────────────────────────────────────────
# Regression tests: Missing ffmpeg binary
# ────────────────────────────────────────────────────


@pytest.mark.unit
async def test_encode_raises_flac_error_on_missing_ffmpeg(dummy_wav: Path) -> None:
    """encode_wav_to_flac raises FlacEncodingError when ffmpeg is not installed.

    Regression: Without wrapped exception, FileNotFoundError propagates
    past the ``except FlacEncodingError`` handler in UploadWorker, causing
    a full crash-loop instead of per-item graceful skip.
    """
    with (
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError(2, "No such file or directory", "ffmpeg"),
        ),
        pytest.raises(FlacEncodingError, match=r"ffmpeg.*not found"),
    ):
        await encode_wav_to_flac(dummy_wav, dummy_wav.parent)


@pytest.mark.unit
async def test_encode_raises_flac_error_on_permission_denied(
    dummy_wav: Path,
) -> None:
    """encode_wav_to_flac wraps PermissionError as FlacEncodingError.

    Guards against edge cases where ffmpeg binary exists but is
    not executable — should be a per-item failure, not a crash.
    """
    with (
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=PermissionError(13, "Permission denied", "ffmpeg"),
        ),
        pytest.raises(FlacEncodingError, match="ffmpeg"),
    ):
        await encode_wav_to_flac(dummy_wav, dummy_wav.parent)
