"""Unit tests for MockInputStream — synthetic audio source.

Tests that MockInputStream generates audio data with the correct dtype,
shape, and feeds it into the pipeline queue at approximately real-time pace.
"""

from __future__ import annotations

import queue
import time
from typing import Any

import numpy as np
import pytest
from silvasonic.recorder.pipeline import MockInputStream, PipelineConfig


@pytest.mark.unit
class TestMockInputStream:
    """Tests for MockInputStream — CI-friendly synthetic audio."""

    def test_generates_correct_dtype_int16(self) -> None:
        """MockInputStream produces int16 data for S16LE format."""
        cfg = PipelineConfig(sample_rate=48000, channels=1, format="S16LE", chunk_size=1024)
        q: queue.Queue[Any] = queue.Queue(maxsize=64)
        mock = MockInputStream(q, cfg)

        mock.start()
        time.sleep(0.1)
        mock.stop()

        assert not q.empty(), "Queue should have received data"
        chunk = q.get_nowait()
        assert chunk.dtype == np.int16

    def test_generates_correct_dtype_int32(self) -> None:
        """MockInputStream produces int32 data for S24LE format."""
        cfg = PipelineConfig(sample_rate=48000, channels=1, format="S24LE", chunk_size=1024)
        q: queue.Queue[Any] = queue.Queue(maxsize=64)
        mock = MockInputStream(q, cfg)

        mock.start()
        time.sleep(0.1)
        mock.stop()

        chunk = q.get_nowait()
        assert chunk.dtype == np.int32

    def test_generates_correct_shape_mono(self) -> None:
        """Mono output has shape (chunk_size, 1)."""
        cfg = PipelineConfig(sample_rate=48000, channels=1, chunk_size=512)
        q: queue.Queue[Any] = queue.Queue(maxsize=64)
        mock = MockInputStream(q, cfg)

        mock.start()
        time.sleep(0.1)
        mock.stop()

        chunk = q.get_nowait()
        assert chunk.shape == (512, 1)

    def test_generates_correct_shape_stereo(self) -> None:
        """Stereo output has shape (chunk_size, 2)."""
        cfg = PipelineConfig(sample_rate=48000, channels=2, chunk_size=256)
        q: queue.Queue[Any] = queue.Queue(maxsize=64)
        mock = MockInputStream(q, cfg)

        mock.start()
        time.sleep(0.1)
        mock.stop()

        chunk = q.get_nowait()
        assert chunk.shape == (256, 2)

    def test_produces_nonzero_data(self) -> None:
        """Generated audio is non-zero (sine wave, not silence)."""
        cfg = PipelineConfig(sample_rate=48000, channels=1, chunk_size=1024)
        q: queue.Queue[Any] = queue.Queue(maxsize=64)
        mock = MockInputStream(q, cfg)

        mock.start()
        time.sleep(0.1)
        mock.stop()

        chunk = q.get_nowait()
        assert np.any(chunk != 0), "Synthetic audio should not be all zeros"

    def test_close_alias(self) -> None:
        """close() is an alias for stop() and does not raise."""
        cfg = PipelineConfig(sample_rate=48000, channels=1, chunk_size=1024)
        q: queue.Queue[Any] = queue.Queue(maxsize=64)
        mock = MockInputStream(q, cfg)

        mock.start()
        time.sleep(0.05)
        mock.close()  # Should not raise

    def test_stop_without_start(self) -> None:
        """stop() is safe to call without start()."""
        cfg = PipelineConfig(sample_rate=48000, channels=1, chunk_size=1024)
        q: queue.Queue[Any] = queue.Queue(maxsize=64)
        mock = MockInputStream(q, cfg)

        mock.stop()  # Should not raise
