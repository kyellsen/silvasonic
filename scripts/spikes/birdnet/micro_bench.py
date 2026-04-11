"""Micro-benchmark: isolate the per-window bottleneck."""

import os
import time

import numpy as np

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
from typing import Any

import birdnetlib  # type: ignore
from ai_edge_litert.interpreter import Interpreter  # type: ignore

MODEL_DIR = os.path.join(os.path.dirname(birdnetlib.__file__), "models/analyzer")
MODEL_PATH = os.path.join(MODEL_DIR, "BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite")
LABELS_PATH = os.path.join(MODEL_DIR, "BirdNET_GLOBAL_6K_V2.4_Labels.txt")

interp = Interpreter(model_path=MODEL_PATH, num_threads=1)
interp.allocate_tensors()
inp_idx = interp.get_input_details()[0]["index"]
out_idx = interp.get_output_details()[0]["index"]
with open(LABELS_PATH) as f:
    labels = [label.strip() for label in f]

window = np.random.uniform(-1, 1, 144000).astype(np.float32)
allowed = set(labels[:163])
MIN_CONF = 0.25


def flat_sigmoid(x: Any, s: float = 1.0) -> Any:
    """Implement flat sigmoid function to match birdnetlib."""
    return 1.0 / (1.0 + np.exp(s * np.clip(x, -15, 15)))


N = 30

# Warm up
for _ in range(3):
    interp.set_tensor(inp_idx, window.reshape(1, 144000))
    interp.invoke()

# Step 1: Pure invoke
t0 = time.perf_counter()
for _ in range(N):
    interp.set_tensor(inp_idx, window.reshape(1, 144000))
    interp.invoke()
    raw = interp.get_tensor(out_idx)[0]
invoke_ms = (time.perf_counter() - t0) / N * 1000

# Step 2: + sigmoid
t0 = time.perf_counter()
for _ in range(N):
    interp.set_tensor(inp_idx, window.reshape(1, 144000))
    interp.invoke()
    raw = interp.get_tensor(out_idx)[0]
    scores = flat_sigmoid(raw, -1.0)
sig_ms = (time.perf_counter() - t0) / N * 1000

# Step 3: Python for-loop over 6522 elements (OUR v3 CODE — THE BOTTLENECK)
t0 = time.perf_counter()
for _ in range(N):
    interp.set_tensor(inp_idx, window.reshape(1, 144000))
    interp.invoke()
    raw = interp.get_tensor(out_idx)[0]
    scores = flat_sigmoid(raw, -1.0)
    dets = []
    for i, score in enumerate(scores):
        if score >= MIN_CONF and labels[i] in allowed:
            parts = labels[i].split("_")
            dets.append({"s": parts[0], "c": parts[1] if len(parts) > 1 else ""})
loop_ms = (time.perf_counter() - t0) / N * 1000

# Step 4: OPTIMIZED — numpy vectorized filtering
allowed_mask = np.array([lbl in allowed for lbl in labels], dtype=bool)
t0 = time.perf_counter()
for _ in range(N):
    interp.set_tensor(inp_idx, window.reshape(1, 144000))
    interp.invoke()
    raw = interp.get_tensor(out_idx)[0]
    scores = flat_sigmoid(raw, -1.0)
    mask = (scores >= MIN_CONF) & allowed_mask
    hit_indices = np.where(mask)[0]
    dets = []
    for idx in hit_indices:
        parts = labels[idx].split("_")
        dets.append({"s": parts[0], "c": parts[1] if len(parts) > 1 else ""})
vec_ms = (time.perf_counter() - t0) / N * 1000

# Results
print(f"Pure invoke:        {invoke_ms:7.2f} ms/window")
print(f"+ sigmoid:          {sig_ms:7.2f} ms/window  (sigmoid: +{sig_ms - invoke_ms:.2f} ms)")
print(f"+ Python for-loop:  {loop_ms:7.2f} ms/window  (loop: +{loop_ms - sig_ms:.2f} ms)")
print(f"+ numpy vectorized: {vec_ms:7.2f} ms/window  (vec:  +{vec_ms - sig_ms:.2f} ms)")
print()
loop_overhead = loop_ms - sig_ms
vec_overhead = vec_ms - sig_ms
print(f"Python loop cost:   {loop_overhead:.2f} ms  (iterating ALL 6522 scores in Python)")
print(f"Numpy vec cost:     {vec_overhead:.2f} ms  (numpy boolean mask + iterate only hits)")
if vec_overhead > 0:
    print(f"Post-proc speedup:  {loop_overhead / vec_overhead:.1f}x")
faster_pct = (1 - vec_ms / loop_ms) * 100
print(f"Total per-window:   {loop_ms:.2f} -> {vec_ms:.2f} ms ({faster_pct:.1f}% faster)")
print(f"Per 3-win segment:  {loop_ms * 3:.0f} -> {vec_ms * 3:.0f} ms")
