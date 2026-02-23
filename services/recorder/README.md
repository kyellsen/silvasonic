# silvasonic-recorder

> **Status:** Partial (v0.1.0) · **Tier:** 2 (Application, Managed by Controller) · **Port:** 9500

**AS-IS:** The Recorder is the most critical service in the Silvasonic stack. It captures audio from USB microphones and writes segmented WAV files to local NVMe storage. Multiple Recorder instances may run concurrently, each managed by the Controller. Implements the Dual Stream Architecture (Raw + Processed), with Triple Stream (+ Live Opus) **TO-BE:** v0.9.0.

---

## The Problem / The Gap

*   **Hardware Abstraction:** Different microphones (USB, I2S) have different sample rates, bit depths, and quirks. A unified capture layer is needed that works with any ALSA-compatible device.
*   **Reliability:** Recording processes can hang, drift, or crash. A robust watchdog must ensure continuous capture and graceful recovery.
*   **Multi-Purpose Audio:** The system needs high-resolution raw data for science, normalized data for ML inference, and low-latency compressed data for live listening — simultaneously from a single microphone input.

## User Benefit

*   **Plug & Play:** Works with any ALSA-compatible USB microphone. Configuration is injected by the Controller via Microphone Profiles.
*   **Live Monitoring:** Listen to the microphone in real-time via Icecast (Opus stream) without stopping or degrading the scientific recording (**TO-BE:** v0.9.0).
*   **Data Quality:** Raw files are untouched (24-bit, native sample rate), ensuring no data loss for downstream analysis.

---

## Immutability Rules

The Recorder is an **immutable Tier 2** service. This means:

- **No database access.** The Recorder has no connection to TimescaleDB or any other database. This is strictly forbidden (ADR-0013).
- **Profile Injection.** All configuration is provided via environment variables set by the Controller at container creation time.
- **No self-modification.** The Recorder does not change its own state or configuration at runtime.
- **Stateless container.** The only persistent artifact is the audio data written to the bind-mounted workspace volume.

---

## Core Responsibilities

### Inputs

*   **Audio Hardware:** ALSA devices via `/dev/snd` hardware mapping. We only support USB microphones for v1.0.0.
*   **Configuration:** Microphone Profile injected as environment variables by the Controller at container creation time (Profile Injection, ADR-0013/ADR-0016). **No database access.**

### Processing

*   **FFmpeg Pipeline:** Orchestrates a filter graph using `ffmpeg-python`. A single ALSA capture is split into multiple output streams.
*   **Dual Stream Architecture** (current target):
    1.  **Raw:** Preserves original sample rate and bit depth (`pcm_s24le`).
    2.  **Processed:** Resamples to 48 kHz (`pcm_s16le`) for consistent ML input.
*   **Segment Writing:** Files are written in 10-second segments by default (this duration can be overridden by the Microphone Profile via the YAML seed/database).
*   **Buffer to Records:** While a 10s segment is being actively written, it is stored in a `.buffer/` directory. Only when the segment is completely written and closed by FFmpeg is it moved to the `records/` directory. This ensures the Processor only picks up complete, valid files.
*   **Triple Stream Architecture** (**TO-BE:** v0.9.0):
    3.  **Live (Opus):** Encodes to Ogg/Opus (64 kbps) and pushes to Icecast mount point. Best-effort — never compromises Data Capture Integrity (ADR-0011).
*   **Watchdog:** Monitors the FFmpeg subprocess via `stderr` for errors, hangs, or death. Restarts the pipeline on failure.

### Outputs

*   **Filesystem:** Segmented WAV files in `records/raw/` and `records/processed/` directories under the Recorder workspace on NVMe (moved there from `.buffer/`).
*   **Icecast Stream:** (**TO-BE:** v0.9.0) Pushes Opus audio directly to an Icecast mount point (e.g., `/mic-ultramic.opus`).
*   **Redis Heartbeats:** Fire-and-forget heartbeats via `SilvaService` base class (ADR-0019). Zero coupling to the recording loop — if Redis is unavailable, heartbeats are silently skipped.

---

## Operational Constraints & Rules

| Aspect           | Value / Rule                                                                             |
| ---------------- | ---------------------------------------------------------------------------------------- |
| **Immutable**    | Yes — config at startup via env vars, restart to reconfigure (ADR-0019)                  |
| **DB Access**    | **No** — the Recorder has zero database access (ADR-0013). Config via Profile Injection. |
| **Concurrency**  | Process-based — core work in FFmpeg subprocess, Python wrapper is threaded (Watchdog)    |
| **State**        | Stateless (no DB) but manages ALSA hardware locks and file handles at runtime            |
| **Privileges**   | Privileged (`privileged: true`) — requires `/dev/snd` and ALSA access (ADR-0007)         |
| **Resources**    | Medium — continuous I/O to NVMe, FFmpeg CPU usage scales with sample rate                |
| **QoS Priority** | `oom_score_adj=-999` — **Protected**. OOM Killer kills this LAST. (ADR-0020)             |

> [!CAUTION]
> The Recorder's `oom_score_adj=-999` makes it the **most protected** process on the system. This is the final line of defense for Data Capture Integrity — all analysis services (BirdNET, BatDetect, Weather) are expendable (`+500`) and will be killed first under memory pressure.

---

## Health Endpoint

The Recorder exposes a health endpoint at `GET /healthy` on port `9500` (internal). This is used by the Compose healthcheck and the Controller to monitor Recorder status.

---

## Lifecycle

- **Not auto-started.** The Recorder uses the `managed` Compose profile and does not start with `just start`.
- **Started by Controller.** The Controller spawns Recorder instances as needed, injecting the appropriate profile (device, sample rate, channel config, segment duration).
- **Graceful shutdown.** The Recorder handles `SIGTERM` and `SIGINT` for clean shutdown.

---

## Configuration & Environment

| Variable / Mount           | Description              | Default / Example                                        |
| -------------------------- | ------------------------ | -------------------------------------------------------- |
| `SILVASONIC_RECORDER_PORT` | Health endpoint port     | `9500`                                                   |
| `RECORDER_DEVICE`          | ALSA device identifier   | `hw:1,0`                                                 |
| `RECORDER_PROFILE`         | Microphone Profile slug  | `ultramic_384_evo`                                       |
| `SILVASONIC_ICECAST_URL`   | Target for Opus Stream   | `icecast://user:pass@host:port/mount`                    |
| `/dev/snd`                 | ALSA audio device access | (device mapping)                                         |
| Workspace mount            | NVMe recording workspace | `${SILVASONIC_WORKSPACE_PATH}/recorder:/app/workspace:z` |

> [!NOTE]
> All `RECORDER_*` variables are injected by the Controller at container creation time (Profile Injection). The user never configures them manually — they are derived from the Microphone Profile assigned to the device.

---

## Technology Stack

*   **Audio Pipeline:** FFmpeg (system binary) + `ffmpeg-python` (graph construction)
*   **Audio Codecs:** `pcm_s24le` (Raw), `pcm_s16le` (Processed), Opus/Ogg (Live)
*   **System Dependencies:** `ffmpeg`, `alsa-utils`
*   **Python:** `silvasonic-core` (SilvaService base class, health monitoring), `structlog` (JSON logging)
*   **Base Image:** `python:3.11-slim-bookworm` (Dockerfile)

---

## Open Questions & Future Ideas

*   FFmpeg vs. GStreamer — GStreamer offers lower-latency ALSA integration but more complex pipeline syntax
*   Automatic gain control based on ambient noise levels

## Out of Scope

*   **Does NOT** compress files to FLAC (Uploader's job).
*   **Does NOT** support I2S microphones for v1.0.0 (USB/ALSA only).
*   **Does NOT** analyze audio (BirdNET / BatDetect / Processor's job).
*   **Does NOT** upload files to the cloud (Uploader's job).
*   **Does NOT** provide a UI (Web-Interface's job).
*   **Does NOT** store metadata in the database (no DB access — ADR-0013).
*   **Does NOT** manage its own container lifecycle (Controller's job).
*   **Does NOT** serve the Icecast endpoint (Icecast's job — Recorder only pushes to it).

---

## Implementation Status

| Feature                  | Status                                         |
| ------------------------ | ---------------------------------------------- |
| Health server            | ✅ Implemented (`:9500/healthy`)                |
| Recording health monitor | ✅ Implemented (placeholder, hardcoded healthy) |
| Signal handling          | ✅ Implemented (graceful shutdown)              |
| Audio capture logic      | **TO-BE:** (v0.4.0)                            |

---

## References

- [ADR-0009: Zero-Trust Data Sharing](../../docs/adr/0009-zero-trust-data-sharing.md) — Consumer Principle
- [ADR-0011: Audio Recording Strategy](../../docs/adr/0011-audio-recording-strategy.md) — Dual/Triple Stream
- [ADR-0013: Tier 2 Container Management](../../docs/adr/0013-tier2-container-management.md) — no DB access
- [ADR-0016: Hybrid YAML/DB Profile Management](../../docs/adr/0016-hybrid-yaml-db-profiles.md)
- [ADR-0019: Unified Service Infrastructure](../../docs/adr/0019-unified-service-infrastructure.md) — SilvaService lifecycle, heartbeats
- [ADR-0020: Resource Limits & QoS](../../docs/adr/0020-resource-limits-qos.md) — oom_score_adj=-999
- [Microphone Profiles](../../docs/arch/microphone_profiles.md) — Profile seed files and format
- [Port Allocation](../../docs/arch/port_allocation.md) — Recorder on port 9500
- [Glossary](../../docs/glossary.md) — Dual/Triple Stream Architecture, Recorder definition
- [ROADMAP.md](../../ROADMAP.md) — roadmap entries
