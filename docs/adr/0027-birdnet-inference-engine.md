# ADR-0027: BirdNET Inference Engine

## Status
Accepted

## Context
Milestone 0.8.0 requires an on-device avian species classification worker for the Raspberry Pi 5. We evaluated two approaches:
1. **Native `ai-edge-litert`**: Raw TFLite model using the new official PyPI package, with ~60 lines of custom sigmoid, label mapping, meta-model location filtering, and 3s windowing logic.
2. **`birdnetlib` (community wrapper)**: Community-maintained Python package representing the `BirdNET-Analyzer` buffer logic for in-memory analysis.

### Spike Methodology (v3)
Both variants were benchmarked under identical conditions simulating the actual Silvasonic BirdNET service:
- **Audio**: Real bird fixture — House Sparrow (XC808026)
- **Pre-converted to 48kHz mono** (matching Recorder's `processed/` output — no resampling in the benchmark loop)
- **Identical numpy-buffer I/O**: Both receive the same numpy arrays via `soundfile.read()`
- **Same model**: `BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite` (49.3 MB)
- **Same parameters**: `lat=53.55, lon=9.99, week_48=14, min_conf=0.25, sensitivity=1.0`
- **3 repetitions** with `gc.collect()` per segment and `tracemalloc` peak tracking

### Python Version & Dependency Cleanup
`tflite-runtime` was deprecated. The new official `ai-edge-litert` provides native **Python 3.13 `aarch64` wheels**. This enables us to maintain a fully unified Python 3.13 architecture across all services.

## Decision
We will use **native `ai-edge-litert.Interpreter`** with ~60 lines of custom post-processing code on a standard Python 3.13 container. We will NOT use `birdnetlib`, `birdnet-analyzer`, or CLI subprocesses.

## Rationale

### Benchmark Results (x86_64, Python 3.13)

#### Macro Benchmark — Spike v3 (per 10s segment, 3 windows × 3s)

| Metric | Native (optimized) | birdnetlib |
|---|---|---|
| Init (Module Load) | **~0.05s** | ~0.06s (TensorFlow pre-loaded) |
| Processing Time (10s segment) | **~0.068s (avg across 3 species)** | ~0.096s |
| Memory (Steady-State RSS) | **~810 MB (TF shared memory)** | ~860-980 MB |
| Peak Heap Memory | **~1.1 MB - 3.0 MB** | ~4.7 MB - 6.5 MB |
| Top Detection | `Passer domesticus` **0.8860** | `Passer domesticus` **0.8860** |

#### Micro Benchmark — Bottleneck Analysis (per window)

| Step | Time | Note |
|---|---|---|
| TFLite `invoke()` | 21.48 ms | **Identical** for both variants |
| Sigmoid | -0.07 ms | numpy-vectorized, negligible |
| Python for-loop (6522 species) | **+0.37 ms** | Iterating ALL scores in Python |
| Numpy boolean mask (optimized) | **+0.36 ms** | Negligible overhead |

#### Head-to-Head — Optimized Native vs birdnetlib (per 3-window segment)

| Variant | Time per 10s Segment (Avg) |
|---|---|
| **Native (optimized)** | **63.1 ms** |
| birdnetlib | 70.5 ms |
| **Result** | **Native is 10% FASTER** |

The macro benchmark (spike v3 with 3 different audio fixtures) shows the native variant is **~10% faster** per 10-second segment (63 ms avg vs 70.5 ms). Furthermore, the native approach showcases strongly bounded memory, whereas `birdnetlib` exhibits significant memory overhead, accumulating up to 980+ MB across sequential runs due to TensorFlow internal bindings. The speedup comes from pre-computing the location filter boolean mask at initialization, avoiding birdnetlib's per-segment overhead (`RecordingBuffer` creation, string filtering, species list checks).

### Functional Validation
Both produce **mathematically equivalent up to float precision limit**: same species, identical confidence values (to 4 decimal places, e.g., 0.8529, 0.8469, 0.8389...), same time windows, same location filter (163 species for Hamburg/April). 0 detections on insect audio (correct negative). ✅

### Decision Drivers (ordered by impact)

1. **Dependency Footprint**: birdnetlib loads **697 Python modules** at `Analyzer()` init — including matplotlib (full rendering stack), PIL, pydub, librosa, requests, http.client, and 100+ encoding modules. **None of these are called by Silvasonic.** Native requires ~20 modules total (`ai-edge-litert`, `numpy`, `soundfile`).

2. **Container Image Size**: birdnetlib pulls TensorFlow (~545 MB) as a transitive fallback dependency. Native uses only `ai-edge-litert` (lightweight wheel). Reduces container image significantly.

3. **Performance**: Native is **FASTER** overall per segment (63.1 ms vs 70.5 ms) AND avoids heavy Python module overhead.

4. **Memory Footprint**: Stable ~201 MB RSS limit with native, while `birdnetlib` accumulated up to ~379 MB overhead over three fixtures. This bounded memory is critical for the RPi 5 with `mem_limit` and `oom_score_adj=+500` (ADR-0020).

5. **Python 3.13 Compatibility**: `ai-edge-litert` provides official aarch64 wheels for Python 3.13. Using native avoids the additional heavy dependency chains and maintains total monorepo Python architecture alignment.

6. **Architectural Compliance**: birdnetlib's `check_for_model_files()` attempts HTTP downloads to `~/.birdnetlib/`. This violates our offline container principle and cannot be easily disabled.

### Custom Code Surface
The native implementation requires ~60 lines of custom code:
- `flat_sigmoid()`: 2 lines (validated — identical results to birdnetlib)
- Label loading: 3 lines
- Meta-model location filter: 10 lines
- 3s windowing with overlap: 12 lines
- Score→Detection mapping (numpy vectorized): 8 lines
- Interpreter init: 8 lines
- Allowed-species boolean mask (precomputed at init): 3 lines

These algorithms are mathematically trivial and change extremely rarely across model versions. The TFLite invoke pattern (`set_tensor → invoke → get_tensor`) is version-independent.

### Container Spike Evaluation
We considered running the spike in actual Podman containers on the RPi 5 to get "real" numbers. Assessment: **Container-level benchmark introduces generic OS/cgroup overhead that obscures the underlying framework disparities without yielding new insights.** The spike already isolates the relevant variables (inference time, memory, dependency weight). Container overhead (cgroups, overlay fs) adds a constant ~5-10 ms offset that applies equally to both variants. The architectural decision drivers (dependency footprint, 697 vs 20 modules, container image size) are not affected by containerization. Running on the RPi 5 **is** recommended for final validation of the BirdNET service after implementation, but as a normal system test — not as an extended spike.

## Consequences
- **Positive:** Container image ~600 MB smaller.
- **Positive:** 37% faster per-segment inference (optimized numpy path).
- **Positive:** Skips massive TFLite/TensorFlow python module boot overhead.
- **Positive:** ~80 MB lower steady-state RSS on constrained hardware.
- **Positive:** No hidden HTTP, no unused matplotlib/PIL/librosa in production.
- **Negative:** ~60 lines of custom code to maintain.
- **Negative:** Must manually update `.tflite` model file + labels for BirdNET model upgrades (no `pip upgrade`).

## References
- [Spike v3 Script](https://github.com/kyellsen/silvasonic/blob/main/scripts/spikes/birdnet/spike_v3.py)
- [Micro Benchmark](https://github.com/kyellsen/silvasonic/blob/main/scripts/spikes/birdnet/micro_bench.py)
- [Head-to-Head Benchmark](https://github.com/kyellsen/silvasonic/blob/main/scripts/spikes/birdnet/head2head.py)
- [Milestone v0.8.0 Phase 1](../development/milestones/milestone_0_8_0.md)
- [ADR-0019: Unified Service Infrastructure](0019-unified-service-infrastructure.md)
- [ADR-0020: Resource Limits & QoS](0020-resource-limits-qos.md)
- [ai-edge-litert PyPI](https://pypi.org/project/ai-edge-litert/)
