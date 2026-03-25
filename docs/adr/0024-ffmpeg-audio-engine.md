# ADR-0024: FFmpeg Audio Engine — Externalizing the Real-Time Audio Path

> **Status:** Accepted • **Date:** 2026-03-25

## 1. Context & Problem

The Recorder service (v0.4.0) captures audio via Python libraries (`sounddevice` + `soundfile` + `soxr`). The PortAudio callback runs in a C thread, but re-enters Python to enqueue data — exposing the audio path to GIL contention and Garbage Collector pauses.

On a Raspberry Pi 5 running concurrent ML workloads (BirdNET, BatDetect), these pauses cause **xruns** (buffer overflows) at high sample rates (384 kHz). This violates **Data Capture Integrity** — the paramount directive (AGENTS.md §1).

## 2. Decision

**We chose:** Replace the Python audio pipeline with an **FFmpeg subprocess** managed by the Recorder service.

**Reasoning:**

*   **GIL-Free Audio Path:** FFmpeg is pure C. No Python code executes in the audio capture path. GIL contention, GC pauses, and `queue.Queue` lock contention become impossible.
*   **Process Isolation:** FFmpeg runs as a separate OS process. If Python crashes, FFmpeg continues recording until SIGTERM. The Linux kernel can schedule FFmpeg on a dedicated CPU core, independent of Python and ML workloads.
*   **Battle-Tested:** FFmpeg is used in billions of installations for audio/video capture. Its ALSA backend, resampler (`soxr`), and segment muxer are production-hardened.
*   **Dual Stream in One Command:** FFmpeg's `-map` and `-f segment` produce both Raw and Processed streams simultaneously — replacing ~600 lines of Python with a single CLI invocation.
*   **Future-Ready:** Adding the Triple Stream (Opus → Icecast, v0.9.0) is a single additional `-map` line.

### 2.1. Segment Completion Strategy

FFmpeg writes segments to `.buffer/raw/` and `.buffer/processed/`. A Python `SegmentPromoter` thread polls FFmpeg's `-segment_list` CSV output and atomically promotes completed segments to `data/` via `os.replace()`.

This preserves the existing `.buffer/` → `data/` promotion pattern required by:
- Filesystem Governance (§2): Processor/Indexer polls `data/` for complete files
- ADR-0009 (Zero-Trust): Consumers mount `data/` as `:ro` — must never see partial files
- DB Schema: `recordings.file_raw` / `recordings.file_processed` reference `data/` paths

### 2.2. Mock Source for CI

`SILVASONIC_RECORDER_MOCK_SOURCE=true` switches FFmpeg from `-f alsa -i hw:X,0` to `-f lavfi -i "sine=frequency=440:sample_rate=48000"` — enabling hardware-independent testing without any Python mock classes.

## 3. Options Considered

*   **Keep Python (`sounddevice` + `soundfile`):** Rejected. Architecturally unsuitable for a 24/7 hardware appliance at 384 kHz with concurrent ML workloads.
*   **Custom Rust CLI (`silvasonic-capture`):** Rejected. Functionally equivalent to FFmpeg but requires maintaining a separate Rust codebase. FFmpeg delivers 99% of the robustness benefit without the development overhead.
*   **FFmpeg writing directly to `data/`:** Rejected. FFmpeg's segment muxer does not guarantee atomic file completion — the Processor/Indexer would see partially-written WAVs.

## 4. Consequences

*   **Positive:**
    *   **Data Capture Integrity guaranteed** at hardware level — no Python in the audio path.
    *   **3 Python dependencies removed** (`sounddevice`, `soundfile`, `soxr`).
    *   **~600 lines of complex Python replaced** by ~250 lines of subprocess management.
    *   **Testable without hardware** via FFmpeg's built-in signal generator (`lavfi`).
    *   **Trivial extension** to Triple Stream (Opus → Icecast) in v0.9.0.
*   **Negative:**
    *   FFmpeg becomes a system-level dependency (installed in Containerfile).
    *   Observability shifts from Python properties to FFmpeg stderr parsing.
    *   `SegmentPromoter` introduces a small promotion latency (~0.5s after segment close).

## 5. References

*   [ADR-0011](0011-audio-recording-strategy.md) — Dual Stream Architecture
*   [ADR-0020](0020-resource-limits-qos.md) — OOM Protection, Recorder = `oom_score_adj=-999`
*   [Filesystem Governance](../arch/filesystem_governance.md) — `.buffer/` → `data/` promotion pattern
*   [Processor Service Spec](../services/processor.md) — Indexer polls `data/` for new WAVs
