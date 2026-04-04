"""BirdNET Architecture Spike v3 — Final Decision Benchmark.

Simulates the ACTUAL conditions of Silvasonic's BirdNET service:
  - Input: 48kHz Mono S16LE WAV (as delivered by Recorder's processed/ output)
  - No resampling needed (spike v2 incorrectly resampled from 44.1→48kHz)
  - Audio read via soundfile (as specified in service docs)
  - Both variants receive identical numpy arrays — no file-write overhead

Variant A:  Native tflite_runtime (full pipeline)
Variant B:  birdnetlib RecordingBuffer (official wrapper, buffer-based)

Both use the SAME:
  - Model: BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite
  - Meta model: BirdNET_GLOBAL_6K_V2.4_MData_Model_V2_FP16.tflite
  - Parameters: lat=53.55, lon=9.99, week_48=14, min_conf=0.25
  - Audio: read once per segment via soundfile, fed as numpy array

Usage:
  python spike_v3.py native   [--reps N]
  python spike_v3.py analyzer [--reps N]
"""

import argparse
import gc
import json
import os
import sys
import time
import tracemalloc
from typing import Any

import numpy as np
import psutil
import soundfile as sf  # type: ignore

# ── Configuration (matching Silvasonic BirdnetSettings + SystemSettings) ──

FIXTURES = [
    {
        "path": os.path.join(
            os.path.dirname(__file__),
            "../../../tests/fixtures/audio",
            "XC521936 - European Robin - Erithacus rubecula.wav",
        ),
        "label": "European Robin",
    },
    {
        "path": os.path.join(
            os.path.dirname(__file__),
            "../../../tests/fixtures/audio",
            "XC589788 - Common Blackbird - Turdus merula.wav",
        ),
        "label": "Common Blackbird",
    },
    {
        "path": os.path.join(
            os.path.dirname(__file__),
            "../../../tests/fixtures/audio",
            "XC808026 - House Sparrow - Passer domesticus.wav",
        ),
        "label": "House Sparrow",
    },
]

MODEL_DIR = os.path.join(
    os.path.dirname(__file__),
    ".venv_311/lib/python3.11/site-packages/birdnetlib/models/analyzer",
)
MODEL_PATH = os.path.join(MODEL_DIR, "BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite")
META_MODEL_PATH = os.path.join(MODEL_DIR, "BirdNET_GLOBAL_6K_V2.4_MData_Model_V2_FP16.tflite")
LABELS_PATH = os.path.join(MODEL_DIR, "BirdNET_GLOBAL_6K_V2.4_Labels.txt")

# BirdNET model expects 48kHz — Silvasonic delivers 48kHz processed WAVs.
# The fixtures are 44.1kHz (xeno-canto downloads), so we pre-convert them
# ONCE at the start to simulate the actual service input accurately.
MODEL_SR = 48000
WINDOW_SECS = 3.0
WINDOW_SAMPLES = int(WINDOW_SECS * MODEL_SR)  # 144000

# Silvasonic config defaults
OVERLAP_SECS = 0.0
MIN_CONF = 0.25
SENSITIVITY = 1.0
LATITUDE = 53.55  # Hamburg
LONGITUDE = 9.99
WEEK_48 = 14  # Early April
LOCATION_FILTER_THRESHOLD = 0.03
SEGMENT_DURATION = 10.0


# ── Utilities ─────────────────────────────────────────────────────────────


def get_rss_mb() -> float:
    """Get global process RSS (high-water mark)."""
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


def flat_sigmoid(x: Any, sensitivity: float = 1.0) -> Any:
    """BirdNET sigmoid (matches birdnetlib/analyzer.py:287-288)."""
    return 1.0 / (1.0 + np.exp(sensitivity * np.clip(x, -15, 15)))


def load_labels() -> list[str]:
    """Load BirdNET labels."""
    with open(LABELS_PATH) as f:
        return [line.strip() for line in f.readlines()]


def load_prepared_fixture(path: str) -> Any:
    """Load a fixture that is already 48kHz, mono, exactly 10s."""
    audio, sr = sf.read(path, dtype="float32")
    assert sr == 48000, f"Fixture {path} must be 48kHz"
    assert len(audio) == 480000, f"Fixture {path} must be exactly 10.0s (480000 samples)"

    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio


def slice_segment_into_windows(
    audio: Any,
    overlap_secs: float = OVERLAP_SECS,
) -> list[Any]:
    """Slice a segment into 3s windows with overlap.

    Matches birdnetlib's process_audio_data() logic:
      - minlen = 1.5s → short tails are padded if >= 1.5s
      - windows shorter than 3s are zero-padded
    """
    step = int((WINDOW_SECS - overlap_secs) * MODEL_SR)
    min_samples = int(1.5 * MODEL_SR)
    windows = []
    for start in range(0, len(audio), step):
        chunk = audio[start : start + WINDOW_SAMPLES]
        if len(chunk) < min_samples:
            break
        if len(chunk) < WINDOW_SAMPLES:
            padded = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
            padded[: len(chunk)] = chunk
            chunk = padded
        windows.append(chunk)
    return windows


# ── Variant A: Native tflite_runtime ─────────────────────────────────────


def benchmark_native(reps: int = 3) -> dict[str, Any]:
    """Run native benchmark."""
    tracemalloc.start()
    baseline_rss = get_rss_mb()
    results: dict[str, Any] = {"variant": "native_tflite_runtime", "reps": reps, "files": []}

    for fixture in FIXTURES:
        file_results: dict[str, Any] = {"fixture": fixture["label"], "runs": []}

        # Load fixture (simulating a processed recording from DB)
        full_audio = load_prepared_fixture(fixture["path"])

        for rep in range(reps):
            gc.collect()
            run: dict[str, Any] = {"rep": rep + 1, "segments": []}

            # ── Init ──
            init_start = time.perf_counter()

            from tflite_runtime.interpreter import Interpreter  # type: ignore

            interpreter = Interpreter(model_path=MODEL_PATH, num_threads=1)
            interpreter.allocate_tensors()
            input_idx = interpreter.get_input_details()[0]["index"]
            output_idx = interpreter.get_output_details()[0]["index"]

            meta_interp = Interpreter(model_path=META_MODEL_PATH, num_threads=1)
            meta_interp.allocate_tensors()
            meta_in_idx = meta_interp.get_input_details()[0]["index"]
            meta_out_idx = meta_interp.get_output_details()[0]["index"]

            labels = load_labels()

            # Location filter via meta model
            meta_input = np.array([[LATITUDE, LONGITUDE, WEEK_48]], dtype=np.float32)
            meta_interp.set_tensor(meta_in_idx, meta_input)
            meta_interp.invoke()
            loc_filter = meta_interp.get_tensor(meta_out_idx)[0]
            allowed_mask = loc_filter >= LOCATION_FILTER_THRESHOLD

            init_time = time.perf_counter() - init_start
            init_rss = get_rss_mb()
            run["init_s"] = round(init_time, 4)
            run["init_rss_mb"] = round(init_rss, 2)
            run["init_delta_mb"] = round(init_rss - baseline_rss, 2)
            run["allowed_species"] = int(np.sum(allowed_mask))

            # ── Process segments ──
            segments = [(0.0, full_audio)]
            all_detections: list[dict[str, Any]] = []

            for seg_offset, seg_audio in segments:
                seg_start = time.perf_counter()
                windows = slice_segment_into_windows(seg_audio, OVERLAP_SECS)
                seg_dets: list[dict[str, Any]] = []

                for w_idx, window in enumerate(windows):
                    w_start = seg_offset + w_idx * (WINDOW_SECS - OVERLAP_SECS)
                    w_end = w_start + WINDOW_SECS

                    interpreter.set_tensor(input_idx, window.reshape(1, WINDOW_SAMPLES))
                    interpreter.invoke()
                    raw = interpreter.get_tensor(output_idx)[0]

                    # Exact birdnetlib sensitivity inversion
                    adj_sens = max(0.5, min(1.0 - (SENSITIVITY - 1.0), 1.5))
                    scores = flat_sigmoid(raw, sensitivity=-adj_sens)

                    mask = (scores >= MIN_CONF) & allowed_mask
                    hits = np.where(mask)[0]
                    for i in hits:
                        score = scores[i]
                        parts = labels[i].split("_")
                        seg_dets.append(
                            {
                                "scientific_name": parts[0],
                                "common_name": (parts[1] if len(parts) > 1 else ""),
                                "confidence": round(float(score), 4),
                                "start_time": round(w_start, 2),
                                "end_time": round(w_end, 2),
                            }
                        )

                seg_time = time.perf_counter() - seg_start
                num_windows = len(windows)
                del windows
                gc.collect()
                run["segments"].append(
                    {
                        "offset_s": seg_offset,
                        "windows": num_windows,
                        "detections": len(seg_dets),
                        "time_s": round(seg_time, 4),
                        "rss_mb": round(get_rss_mb(), 2),
                    }
                )
                all_detections.extend(seg_dets)

            # Summary
            stimes = [s["time_s"] for s in run["segments"]]
            run["total_segments"] = len(segments)
            run["total_detections"] = len(all_detections)
            run["first_seg_s"] = stimes[0] if stimes else 0
            run["avg_seg_s"] = round(sum(stimes[1:]) / len(stimes[1:]), 4) if len(stimes) > 1 else 0
            run["total_proc_s"] = round(sum(stimes), 4)
            run["final_rss_mb"] = round(get_rss_mb(), 2)
            run["peak_heap_mb"] = round(tracemalloc.get_traced_memory()[1] / 1024 / 1024, 2)
            run["top5"] = sorted(all_detections, key=lambda d: d["confidence"], reverse=True)[:5]
            file_results["runs"].append(run)
            tracemalloc.clear_traces()

        results["files"].append(file_results)

    tracemalloc.stop()
    return results


# ── Variant B: birdnetlib RecordingBuffer ─────────────────────────────────


def benchmark_analyzer(reps: int = 3) -> dict[str, Any]:
    """Run analyzer benchmark."""
    tracemalloc.start()
    baseline_rss = get_rss_mb()
    results: dict[str, Any] = {"variant": "birdnetlib_analyzer", "reps": reps, "files": []}

    for fixture in FIXTURES:
        file_results: dict[str, Any] = {"fixture": fixture["label"], "runs": []}
        full_audio = load_prepared_fixture(fixture["path"])

        for rep in range(reps):
            gc.collect()
            run: dict[str, Any] = {"rep": rep + 1, "segments": []}

            # ── Init ──
            init_start = time.perf_counter()
            os.environ["CUDA_VISIBLE_DEVICES"] = ""

            from birdnetlib.analyzer import Analyzer  # type: ignore
            from birdnetlib.main import RecordingBuffer  # type: ignore

            analyzer = Analyzer()

            init_time = time.perf_counter() - init_start
            init_rss = get_rss_mb()
            run["init_s"] = round(init_time, 4)
            run["init_rss_mb"] = round(init_rss, 2)
            run["init_delta_mb"] = round(init_rss - baseline_rss, 2)

            # ── Process segments ──
            segments = [(0.0, full_audio)]
            all_detections: list[dict[str, Any]] = []

            for seg_offset, seg_audio in segments:
                seg_start = time.perf_counter()

                recording = RecordingBuffer(
                    analyzer,
                    seg_audio,
                    MODEL_SR,
                    lat=LATITUDE,
                    lon=LONGITUDE,
                    week_48=WEEK_48,
                    min_conf=MIN_CONF,
                    sensitivity=SENSITIVITY,
                    overlap=OVERLAP_SECS,
                )
                recording.analyze()
                seg_dets = recording.detections

                seg_time = time.perf_counter() - seg_start
                del recording
                gc.collect()
                run["segments"].append(
                    {
                        "offset_s": seg_offset,
                        "detections": len(seg_dets),
                        "time_s": round(seg_time, 4),
                        "rss_mb": round(get_rss_mb(), 2),
                    }
                )
                all_detections.extend(seg_dets)

            stimes = [s["time_s"] for s in run["segments"]]
            run["total_segments"] = len(segments)
            run["total_detections"] = len(all_detections)
            run["first_seg_s"] = stimes[0] if stimes else 0
            run["avg_seg_s"] = round(sum(stimes[1:]) / len(stimes[1:]), 4) if len(stimes) > 1 else 0
            run["total_proc_s"] = round(sum(stimes), 4)
            run["final_rss_mb"] = round(get_rss_mb(), 2)
            run["peak_heap_mb"] = round(tracemalloc.get_traced_memory()[1] / 1024 / 1024, 2)
            run["top5"] = sorted(all_detections, key=lambda d: d["confidence"], reverse=True)[:5]
            file_results["runs"].append(run)

        results["files"].append(file_results)

    tracemalloc.stop()
    return results


# ── Pretty Printer ────────────────────────────────────────────────────────


def print_results(results: dict[str, Any]) -> None:
    """Print results cleanly."""
    variant = results["variant"]
    print(f"\n{'═' * 72}")
    print(f"  SPIKE v3 — {variant}")
    print(f"  Config: lat={LATITUDE}, lon={LONGITUDE}, week={WEEK_48}")
    print(f"  Config: min_conf={MIN_CONF}, sensitivity={SENSITIVITY}")
    print(f"  Config: overlap={OVERLAP_SECS}s, window={WINDOW_SECS}s")
    print(f"{'═' * 72}")

    for file_res in results["files"]:
        print(f"\n{'─' * 72}")
        print(f"  Fixture: {file_res['fixture']}")
        print(f"{'─' * 72}")

        for run in file_res["runs"]:
            print(f"\n  ── Run {run['rep']}/{results['reps']} ──")
            print(f"    Init:        {run['init_s']:.4f}s")
            print(f"    Init RSS:    {run['init_rss_mb']:.2f} MB (+{run['init_delta_mb']:.2f})")
            if "allowed_species" in run:
                print(f"    Species:     {run['allowed_species']}")
            print(f"    Segments:    {run['total_segments']}")
            print(f"    First seg:   {run['first_seg_s']:.4f}s")
            print(f"    Avg seg:     {run['avg_seg_s']:.4f}s")
            print(f"    Total proc:  {run['total_proc_s']:.4f}s")
            print(f"    Detections:  {run['total_detections']}")
            print(f"    Final RSS:   {run['final_rss_mb']:.2f} MB")
            print(f"    Peak heap:   {run['peak_heap_mb']:.2f} MB")

            # Segment table
            print(f"    ┌{'─' * 52}┐")
            print(f"    │ {'Seg':>3} │ {'Offset':>7} │ {'Time':>8} │ {'Det':>4} │ {'RSS':>8} │")
            print(f"    ├{'─' * 52}┤")
            for idx, s in enumerate(run["segments"]):
                print(
                    f"    │ {idx + 1:3d} │"
                    f" {s['offset_s']:6.1f}s │"
                    f" {s['time_s']:7.4f}s │"
                    f" {s['detections']:4d} │"
                    f" {s['rss_mb']:7.2f} │"
                )
            print(f"    └{'─' * 52}┘")

            if run["top5"]:
                print("    Top detections:")
                for d in run["top5"]:
                    name = d.get("common_name", "?")
                    sci = d.get("scientific_name", "")
                    print(
                        f"      {d['confidence']:.4f}  {sci}_{name}"
                        f"  [{d['start_time']:.1f}s-{d['end_time']:.1f}s]"
                    )
    print()


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BirdNET Spike v3")
    parser.add_argument(
        "variant",
        choices=["native", "analyzer"],
    )
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    for f in FIXTURES:
        if not os.path.exists(f["path"]):
            print(f"ERROR: Fixture not found: {f['path']}")
            sys.exit(1)

    if args.variant == "native":
        res = benchmark_native(reps=args.reps)
    else:
        res = benchmark_analyzer(reps=args.reps)

    if args.json:
        print(json.dumps(res, indent=2, default=str))
    else:
        print_results(res)
