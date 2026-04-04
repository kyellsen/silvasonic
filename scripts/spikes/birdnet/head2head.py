"""Side-by-side micro-benchmark of IDENTICAL 3-window segment processing."""

import os
import time

import numpy as np

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
from typing import Any

import soundfile as sf  # type: ignore
from tflite_runtime.interpreter import Interpreter  # type: ignore

MODEL_DIR = ".venv_311/lib/python3.11/site-packages/birdnetlib/models/analyzer"
MODEL_PATH = os.path.join(MODEL_DIR, "BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite")
LABELS_PATH = os.path.join(MODEL_DIR, "BirdNET_GLOBAL_6K_V2.4_Labels.txt")

# Load real audio fixture, convert to 48kHz
audio, sr = sf.read(
    os.path.join(
        os.path.dirname(__file__),
        "../../../tests/fixtures/audio",
        "XC808026 - House Sparrow - Passer domesticus.wav",
    ),
    dtype="float32",
)
if audio.ndim > 1:
    audio = audio.mean(axis=1)
target_len = int(len(audio) * 48000 / sr)
audio = np.interp(np.linspace(0, len(audio) - 1, target_len), np.arange(len(audio)), audio).astype(
    np.float32
)

# Take first 10s segment
seg = audio[:480000]
# Slice into 3 windows
windows = [seg[0:144000], seg[144000:288000], seg[288000:432000]]

N = 30  # repetitions

# ── NATIVE (optimized) ─────────────────────────
interp = Interpreter(model_path=MODEL_PATH, num_threads=1)
interp.allocate_tensors()
inp_idx = interp.get_input_details()[0]["index"]
out_idx = interp.get_output_details()[0]["index"]
with open(LABELS_PATH) as f:
    labels = [label.strip() for label in f]

# Pre-compute allowed mask (done once at init, not per segment)
allowed_mask = np.ones(len(labels), dtype=bool)  # no location filter for parity


def flat_sigmoid(x: Any) -> Any:
    """Implement flat sigmoid function to match birdnetlib."""
    return 1.0 / (1.0 + np.exp(-1.0 * np.clip(x, -15, 15)))


# Warm up
for w in windows:
    interp.set_tensor(inp_idx, w.reshape(1, 144000))
    interp.invoke()

times_native = []
for _ in range(N):
    t0 = time.perf_counter()
    for w in windows:
        interp.set_tensor(inp_idx, w.reshape(1, 144000))
        interp.invoke()
        raw = interp.get_tensor(out_idx)[0]
        scores = flat_sigmoid(raw)
        mask = (scores >= 0.25) & allowed_mask
        hits = np.where(mask)[0]
        dets = [{"s": labels[i].split("_")[0], "c": float(scores[i])} for i in hits]
    times_native.append((time.perf_counter() - t0) * 1000)

# ── BIRDNETLIB (RecordingBuffer) ─────────────────
from birdnetlib.analyzer import Analyzer  # type: ignore  # noqa: E402
from birdnetlib.main import RecordingBuffer  # type: ignore  # noqa: E402

analyzer = Analyzer()

times_lib = []
for _ in range(N):
    t0 = time.perf_counter()
    rec = RecordingBuffer(analyzer, seg.copy(), 48000, min_conf=0.25, sensitivity=1.0)
    rec.analyze()
    _ = rec.detections
    times_lib.append((time.perf_counter() - t0) * 1000)

# ── Results ──
native_avg = sum(times_native) / N
lib_avg = sum(times_lib) / N
native_med = sorted(times_native)[N // 2]
lib_med = sorted(times_lib)[N // 2]

print(
    f"NATIVE (optimized):  avg={native_avg:.1f} ms  median={native_med:.1f} ms  (per 3-win segment)"
)
print(f"BIRDNETLIB:          avg={lib_avg:.1f} ms  median={lib_med:.1f} ms  (per 3-win segment)")
print(f"Ratio:               native/lib = {native_avg / lib_avg:.2f}x")
if native_avg < lib_avg:
    print(f"=> Native is {(1 - native_avg / lib_avg) * 100:.0f}% FASTER")
else:
    print(f"=> birdnetlib is {(1 - lib_avg / native_avg) * 100:.0f}% faster")
