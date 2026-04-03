"""Integration tests for the FLAC encoder against a real ffmpeg subprocess."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf  # type: ignore[import-untyped]
from silvasonic.processor.modules.flac_encoder import encode_wav_to_flac


@pytest.fixture
def synthetic_wav(tmp_path: Path) -> Path:
    """Create a real, highly compressible 1-second synthetic WAV file using numpy."""
    sample_rate = 48000
    duration_s = 1.0
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)

    # 440 Hz Sine wave (Highly compressible by FLAC)
    audio = 0.5 * np.sin(2 * np.pi * 440 * t)

    wav_path = tmp_path / "test_audio.wav"
    sf.write(wav_path, audio, sample_rate, format="WAV", subtype="PCM_16")

    return wav_path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_wav_to_flac(synthetic_wav: Path) -> None:
    """Verify that encode_wav_to_flac successfully uses ffmpeg to create a FLAC file.

    This ensures the CLI arguments inside the Python module are syntactically
    correct for the ffmpeg binary installed in our environment.
    """
    output_dir = synthetic_wav.parent
    result_flac = await encode_wav_to_flac(synthetic_wav, output_dir)

    assert result_flac.exists(), "FLAC file was not created by ffmpeg"
    assert result_flac.suffix == ".flac", "Output file does not have .flac extension"
    assert result_flac.stat().st_size > 0, "FLAC file is empty"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_flac_smaller_than_wav(synthetic_wav: Path) -> None:
    """Verify that FLAC compression actually reduces file size.

    Since the synthetic WAV is a simple sine wave, FLAC compression should easily
    achieve significant size reduction.
    """
    output_dir = synthetic_wav.parent
    result_flac = await encode_wav_to_flac(synthetic_wav, output_dir)

    wav_size = synthetic_wav.stat().st_size
    flac_size = result_flac.stat().st_size

    # Due to being a pure sine wave, FLAC compression should be excellent
    assert flac_size < wav_size, f"FLAC ({flac_size}b) is not smaller than WAV ({wav_size}b)"
    assert flac_size < (wav_size * 0.7), "FLAC compression ratio is unexpectedly poor"
