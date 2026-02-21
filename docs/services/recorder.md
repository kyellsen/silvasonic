# Recorder Service

> **Status:** Implemented (v0.1.0, Scaffold) · **Tier:** 2 · **Instances:** Multi-instance (one per microphone) · **Port:** 9500 (health)

The most critical service — captures audio from USB microphones and writes segmented WAV files to local NVMe storage. Implements the Dual Stream Architecture (Raw + Processed), with Triple Stream (+ Live Opus) planned for v0.9.0.

---

## 1. The Problem / The Gap

*   **Hardware Abstraction:** Different microphones (USB, I2S) have different sample rates, bit depths, and quirks. A unified capture layer is needed that works with any ALSA-compatible device.
*   **Reliability:** Recording processes can hang, drift, or crash. A robust watchdog must ensure continuous capture and graceful recovery.
*   **Multi-Purpose Audio:** The system needs high-resolution raw data for science, normalized data for ML inference, and low-latency compressed data for live listening — simultaneously from a single microphone input.

## 2. User Benefit

*   **Plug & Play:** Works with any ALSA-compatible USB microphone. Configuration is injected by the Controller via Microphone Profiles.
*   **Live Monitoring:** Listen to the microphone in real-time via Icecast (Opus stream) without stopping or degrading the scientific recording (v0.9.0).
*   **Data Quality:** Raw files are untouched (24-bit, native sample rate), ensuring no data loss for downstream analysis.

## 3. Core Responsibilities

### Inputs

*   **Audio Hardware:** ALSA devices via `/dev/snd` hardware mapping.
*   **Configuration:** Microphone Profile injected as environment variables by the Controller at container creation time (Profile Injection, ADR-0013/ADR-0016). **No database access.**

### Processing

*   **FFmpeg Pipeline:** Orchestrates a filter graph using `ffmpeg-python`. A single ALSA capture is split into multiple output streams.
*   **Dual Stream Architecture** (current target):
    1.  **Raw:** Preserves original sample rate and bit depth (`pcm_s24le`). Written to `raw/` directory.
    2.  **Processed:** Resamples to 48 kHz (`pcm_s16le`) for consistent ML input. Written to `processed/` directory.
*   **Triple Stream Architecture** (v0.9.0):
    3.  **Live (Opus):** Encodes to Ogg/Opus (64 kbps) and pushes to Icecast mount point. Best-effort — never compromises Data Capture Integrity (ADR-0011).
*   **Watchdog:** Monitors the FFmpeg subprocess via `stderr` for errors, hangs, or death. Restarts the pipeline on failure.

### Outputs

*   **Filesystem:** Segmented WAV files in `raw/` and `processed/` directories under the Recorder workspace on NVMe.
*   **Icecast Stream:** (v0.9.0) Pushes Opus audio directly to an Icecast mount point (e.g., `/mic-ultramic.opus`).
*   **Redis Heartbeats:** Fire-and-forget heartbeats via `SilvaService` base class (ADR-0019). Zero coupling to the recording loop — if Redis is unavailable, heartbeats are silently skipped.

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                                             |
| ---------------- | ---------------------------------------------------------------------------------------- |
| **Immutable**    | Yes — config at startup via env vars, restart to reconfigure (ADR-0019)                  |
| **DB Access**    | **No** — the Recorder has zero database access (ADR-0013). Config via Profile Injection. |
| **Concurrency**  | Process-based — core work in FFmpeg subprocess, Python wrapper is threaded (Watchdog)    |
| **State**        | Stateless (no DB) but manages ALSA hardware locks and file handles at runtime            |
| **Privileges**   | Privileged (`privileged: true`) — requires `/dev/snd`, ALSA, and GPIO access (ADR-0007)  |
| **Resources**    | Medium — continuous I/O to NVMe, FFmpeg CPU usage scales with sample rate                |
| **QoS Priority** | `oom_score_adj=-999` — **Protected**. OOM Killer kills this LAST. (ADR-0020)             |

> [!CAUTION]
> The Recorder's `oom_score_adj=-999` makes it the **most protected** process on the system. This is the final line of defense for Data Capture Integrity — all analysis services (BirdNET, BatDetect, Weather) are expendable (`+500`) and will be killed first under memory pressure.

## 5. Configuration & Environment

| Variable / Mount           | Description              | Default / Example                                        |
| -------------------------- | ------------------------ | -------------------------------------------------------- |
| `SILVASONIC_RECORDER_PORT` | Health endpoint port     | `9500`                                                   |
| `RECORDER_DEVICE`          | ALSA device identifier   | `hw:1,0`                                                 |
| `RECORDER_PROFILE`         | Microphone Profile slug  | `ultramic_384_evo`                                       |
| `/dev/snd`                 | ALSA audio device access | (device mapping)                                         |
| Workspace mount            | NVMe recording workspace | `${SILVASONIC_WORKSPACE_PATH}/recorder:/app/workspace:z` |

> [!NOTE]
> All `RECORDER_*` variables are injected by the Controller at container creation time (Profile Injection). The user never configures them manually — they are derived from the Microphone Profile assigned to the device.

## 6. Technology Stack

*   **Audio Pipeline:** FFmpeg (system binary) + `ffmpeg-python` (graph construction)
*   **Audio Codecs:** `pcm_s24le` (Raw), `pcm_s16le` (Processed), Opus/Ogg (Live)
*   **System Dependencies:** `ffmpeg`, `alsa-utils`
*   **Python:** `silvasonic-core` (SilvaService base class, health monitoring)

## 7. Open Questions & Future Ideas

*   FFmpeg vs. GStreamer — GStreamer offers lower-latency ALSA integration but more complex pipeline syntax
*   Segment duration tuning (currently planned: 5-minute WAV segments)
*   FLAC compression for processed stream (reduces NVMe write volume)
*   I2S microphone support (e.g., ICS-43434) in addition to USB/ALSA
*   Automatic gain control based on ambient noise levels

## 8. Out of Scope

*   **Does NOT** analyze audio (BirdNET / BatDetect / Processor's job).
*   **Does NOT** upload files to the cloud (Uploader's job).
*   **Does NOT** provide a UI (Web-Interface's job).
*   **Does NOT** store metadata in the database (no DB access — ADR-0013).
*   **Does NOT** manage its own container lifecycle (Controller's job).
*   **Does NOT** serve the Icecast endpoint (Icecast's job — Recorder only pushes to it).

## 9. References

*   [Recorder README](../../services/recorder/README.md) — implementation-specific details and status
*   [ADR-0009](../adr/0009-zero-trust-data-sharing.md) — Zero-Trust Data Sharing (Consumer Principle)
*   [ADR-0011](../adr/0011-audio-recording-strategy.md) — Audio Recording Strategy (Dual/Triple Stream)
*   [ADR-0013](../adr/0013-tier2-container-management.md) — Tier 2 Container Management (no DB access)
*   [ADR-0016](../adr/0016-hybrid-yaml-db-profiles.md) — Hybrid YAML/DB Profile Management
*   [ADR-0019](../adr/0019-unified-service-infrastructure.md) — SilvaService lifecycle, heartbeats
*   [ADR-0020](../adr/0020-resource-limits-qos.md) — Resource Limits & QoS (oom_score_adj=-999)
*   [Microphone Profiles](../arch/microphone_profiles.md) — Profile seed files and format
*   [Port Allocation](../arch/port_allocation.md) — Recorder on port 9500
*   [Glossary](../glossary.md) — Dual/Triple Stream Architecture, Recorder definition
*   [VISION.md](../../VISION.md) — roadmap entries
