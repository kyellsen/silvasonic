# silvasonic-recorder

> **Status:** Implemented (since v0.4.0) · **Tier:** 2 (Application, Managed by Controller) · **Port:** 9500

**AS-IS:** The Recorder is the most critical service in the Silvasonic stack. It captures audio from USB microphones and writes segmented WAV files to local NVMe storage. Multiple Recorder instances may run concurrently, each managed by the Controller.
**Target:** Implements the Dual Stream Architecture (Raw + Processed), with Triple Stream (+ Live Opus) 🔮 Future (v1.1.0).

---

## 1. The Problem / The Gap

*   **Hardware Abstraction:** Different microphones (USB, I2S) have different sample rates, bit depths, and quirks. A unified capture layer is needed that works with any ALSA-compatible device.
*   **Reliability:** Recording processes can hang, drift, or crash. A robust watchdog must ensure continuous capture and graceful recovery.
*   **Multi-Purpose Audio:** The system needs high-resolution raw data for science, normalized data for ML inference, and low-latency compressed data for live listening — simultaneously from a single microphone input.

## 2. User Benefit

*   **Plug & Play:** Works with any ALSA-compatible USB microphone. Configuration is injected by the Controller via Microphone Profiles — no manual setup needed. (US-R01)
*   **Uninterrupted Recording:** The recording continues under all circumstances — memory pressure, network failure, or service restarts. Data capture always has priority. (US-R02)
*   **Dual Format:** Simultaneous raw (24-bit, native SR) and processed (48 kHz, 16-bit) output for science and ML. (US-R03)
*   **Live Monitoring:** Listen to the microphone in real-time via Icecast (Opus stream) without stopping or degrading the scientific recording. 🔮 Future (v1.1.0) (US-R04)
*   **Multi-Microphone:** Run multiple microphones in parallel, each with its own isolated instance and workspace. (US-R05)
*   **Self-Healing:** Automatic recovery from pipeline crashes, hangs, and hardware errors — without user intervention. (US-R06)
*   **Configurable Segments:** Segment duration is configurable via Microphone Profile (default: 10s). (US-R07)

---

## 3. Core Responsibilities

### Inputs

*   **Audio Hardware:** ALSA devices via `/dev/snd` hardware mapping. We only support USB microphones for v1.0.0.
*   **Configuration:** Microphone Profile injected as environment variables by the Controller at container creation time (Profile Injection, ADR-0013/ADR-0016). **No database access.**

### Processing

*   **Audio Pipeline:** Subprocess-based engine managing an `ffmpeg` instance. A single ALSA capture is split into multiple output streams in one command (ADR-0024).
*   **Dual Stream Architecture** ✅ Implemented (v0.4.0):
    1.  **Raw:** Preserves original sample rate and bit depth (direct write via FFmpeg).
    2.  **Processed:** Resampled to 48 kHz / S16LE by FFmpeg for consistent ML input.
*   **Segment Writing:** Files are written in configurable segments (default: 10 seconds, configurable via Microphone Profile).
*   **Buffer → Data Workflow:** While a segment is being actively written by FFmpeg, it is stored in `.buffer/{stream}/`. A background promotion routine detects completed segments and atomically moves them to `data/{stream}/`. This ensures the Processor only picks up complete, valid files.
*   **Triple Stream Architecture** 🔮 Future (v1.1.0):
    3.  **Live (Opus):** Encodes to Ogg/Opus (64 kbps) and pushes to Icecast mount point. Best-effort — never compromises Data Capture Integrity (ADR-0011).

### Outputs

*   **Filesystem:** Segmented WAV files in `data/raw/` and `data/processed/` directories under the Recorder instance workspace on NVMe (moved there from `.buffer/`).
*   **Icecast Stream:** 🔮 Future (v1.1.0) — Pushes Opus audio directly to an Icecast mount point (e.g., `/mic-ultramic.opus`).
*   **Redis Heartbeats:** Fire-and-forget heartbeats via `SilvaService` base class (ADR-0019). Zero coupling to the recording loop — if Redis is unavailable, heartbeats are silently skipped.

---

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                                             |
| ---------------- | ---------------------------------------------------------------------------------------- |
| **Immutable**    | Yes — config at startup via env vars, restart to reconfigure (ADR-0019)                  |
| **DB Access**    | **No** — the Recorder has zero database access (ADR-0013). Config via Profile Injection. |
| **Concurrency**  | Multi-process — audio capture is isolated in an FFmpeg subprocess, Python wrapper handles orchestration |
| **State**        | Stateless (no DB) but manages ALSA hardware locks and file handles at runtime            |
| **Privileges**   | Privileged (`privileged: true`) — requires `/dev/snd` and ALSA access (ADR-0007)         |
| **Resources**    | Medium — continuous I/O to NVMe, FFmpeg resampling CPU usage scales with sample rate     |
| **QoS Priority** | `oom_score_adj=-999` — **Protected**. OOM Killer kills this LAST. (ADR-0020)             |
| **Retry Limit**  | Container restart limits apply to prevent infinite loops (managed by Controller)         |

---

## 5. Configuration & Environment

### Infrastructure (.env / Container Variables)
*(Only list variables/mounts required before the container starts. Never list dynamic DB tuning parameters here).*

| Variable / Mount                    | Description                                        | Default / Example                                                      |
| ----------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------- |
| `SILVASONIC_RECORDER_PORT`          | Health endpoint port                               | `9500`                                                                 |
| `SILVASONIC_RECORDER_DEVICE`        | ALSA device identifier                             | `hw:1,0`                                                               |
| `SILVASONIC_RECORDER_PROFILE_SLUG`  | Microphone Profile slug                            | `ultramic_384_evo`                                                     |
| `SILVASONIC_RECORDER_CONFIG_JSON`   | Full profile configuration parameters              | `{"audio":{"sample_rate":384000,...}}`                                 |
| `SILVASONIC_ICECAST_URL`            | Target for Opus Stream                             | `icecast://user:pass@host:port/mount`                                  |
| `/dev/snd`                          | ALSA audio device access                           | (device mapping)                                                       |
| Workspace mount                     | NVMe recording workspace (instance-isolated)       | `${SILVASONIC_WORKSPACE_PATH}/recorder/{workspace_dir}:/app/workspace:z` |

### Application Settings (Dynamic)

> [!NOTE]
> Managed centrally via DB / Pydantic. See [Configuration Architecture](../../docs/adr/0023-configuration-management.md) for factory defaults and developer overrides.
> *(Note: The Recorder itself has no DB access and config is injected by the Controller via Profile Injection).*

---

## 6. Technology Stack

*   **Audio Engine:** `ffmpeg` (subprocess management and capture)
*   **System Dependencies:** `ffmpeg`, `alsa-utils`
*   **Python:** `silvasonic-core` (SilvaService base class, health monitoring), `structlog` (JSON logging)
*   **Base Image:** `python:3.13-slim-bookworm` (Dockerfile)

---

## 7. Out of Scope

*   **Does NOT** compress files to FLAC (Processor Cloud-Sync-Worker's job).
*   **Does NOT** support I2S microphones for v1.0.0 (USB/ALSA only).
*   **Does NOT** analyze audio (BirdNET / BatDetect / Processor's job).
*   **Does NOT** upload files to the cloud (Processor Cloud-Sync-Worker's job).
*   **Does NOT** provide a UI (Web-Interface's job).
*   **Does NOT** store metadata in the database (no DB access — ADR-0013).
*   **Does NOT** manage its own container lifecycle (Controller's job).
*   **Does NOT** serve the Icecast endpoint (Icecast's job — Recorder only pushes to it).
*   **Does NOT** activate/deactivate individual microphones (Controller's job).

---

## 8. Implementation Details (Domain Specific)
### Immutability Rules

The Recorder is an **immutable Tier 2** service. This means:

- **No database access.** The Recorder has no connection to TimescaleDB or any other database. This is strictly forbidden (ADR-0013).
- **Profile Injection.** All configuration is provided via environment variables set by the Controller at container creation time.
- **No self-modification.** The Recorder does not change its own state or configuration at runtime.
- **Stateless container.** The only persistent artifact is the audio data written to the bind-mounted workspace volume.

---

### Workspace & Path Structure

Each Recorder instance gets its own **isolated** workspace directory. The Controller mounts **only** the instance-specific subdirectory into the container — the Recorder never sees the parent `recorder/` directory (ADR-0009, US-R02).

**Host layout** (managed by Controller):
```
workspace/recorder/
└── {workspace_dir}/          # e.g. "ultramic-384-evo-034f"
    ├── data/
    │   ├── raw/              # pcm_s24le, native sample rate
    │   │   └── YYYY-MM-DDTHH-MM-SSZ_{duration}s_{run_id}_{seq}.wav
    │   └── processed/        # pcm_s16le, 48 kHz
    │       └── YYYY-MM-DDTHH-MM-SSZ_{duration}s_{run_id}_{seq}.wav
    └── .buffer/
        ├── raw/
        │   └── *.wav         # actively being written
        └── processed/
            └── *.wav
```

**Container view** (`/app/workspace`):
```
/app/workspace/
├── data/raw/YYYY-MM-DDTHH-MM-SSZ_{duration}s_{run_id}_{seq}.wav
├── data/processed/YYYY-MM-DDTHH-MM-SSZ_{duration}s_{run_id}_{seq}.wav
├── .buffer/raw/*.wav
└── .buffer/processed/*.wav
```

> [!IMPORTANT]
> The Processor reads **only** from `data/`. Files in `.buffer/` are incomplete and must not be touched.

---

### Reliability & Recovery

The Recorder implements multiple layers of protection to ensure Data Capture Integrity (ADR-0011):

### OOM Protection

*   **Highest QoS Priority / Protected Status**. The Recorder is configured to be the last service terminated under memory pressure (ADR-0020).
*   All analysis services (BirdNET, BatDetect, Weather) are expendable (`+500`) and will be killed first under memory pressure.

> [!CAUTION]
> The Recorder's protected status makes it the **most protected** process on the system. This is the final line of defense for Data Capture Integrity.

### Multi-Level Recovery

| Level | Mechanism                                                                                       | Scope                                      |
| ----- | ----------------------------------------------------------------------------------------------- | ------------------------------------------ |
| 1     | **Subprocess Monitor** — monitors the FFmpeg process state and checks for errors or hangs       | Restarts the pipeline within the container |
| 2     | **Container Restart** — Container engine restarts the entire container according to its policy  | Handles container-level crashes            |
| 3     | **Controller Health Check** (reconciliation interval) — detects unresponsive Recorders and recreates them | Handles unrecoverable states               |

### Retry Limits

*   Container restart policies (e.g., `restart: on-failure`) apply to prevent infinite restart loops from persistent hardware errors. The exact configuration is managed by the Controller's container specification.

### Independence

*   A Redis outage does **not** stop the recording — heartbeats are silently skipped.
*   A Controller outage does **not** stop running Recorders — they continue independently.

---

### Multi-Instance Operation

*   One Recorder container per USB microphone.
*   Each instance has its own isolated workspace (`recorder/{name}/`).
*   Instances are spawned by the Controller, each with its own profile injection.
*   Activation/deactivation of individual microphones is a **Controller responsibility** (via database / web interface).

---

## 9. References

- [ADR-0009: Zero-Trust Data Sharing](../../docs/adr/0009-zero-trust-data-sharing.md) — Consumer Principle
- [ADR-0011: Audio Recording Strategy](../../docs/adr/0011-audio-recording-strategy.md) — Dual/Triple Stream
- [ADR-0013: Tier 2 Container Management](../../docs/adr/0013-tier2-container-management.md) — no DB access
- [ADR-0016: Hybrid YAML/DB Profile Management](../../docs/adr/0016-hybrid-yaml-db-profiles.md)
- [ADR-0019: Unified Service Infrastructure](../../docs/adr/0019-unified-service-infrastructure.md) — SilvaService lifecycle, heartbeats
- [ADR-0020: Resource Limits & QoS](../../docs/adr/0020-resource-limits-qos.md) — oom_score_adj=-999
- [Microphone Profiles](../../docs/arch/microphone_profiles.md) — Profile format (seed files live with the Controller)
- [Port Allocation](../../docs/arch/port_allocation.md) — Recorder on port 9500
- [Glossary](../../docs/glossary.md) — Dual/Triple Stream Architecture, Recorder definition
- [User Stories — Recorder](../../docs/user_stories/recorder.md) — US-R01 through US-R07
- [ROADMAP.md](../../ROADMAP.md) — roadmap entries
