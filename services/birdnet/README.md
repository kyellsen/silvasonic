# silvasonic-birdnet

> **Status:** Implemented (since v0.8.0) · **Tier:** 2 (Application, Managed by Controller) · **Instances:** Single · **Port:** 9500
>
> 📋 **User Stories:** [birdnet.md](../../docs/user_stories/birdnet.md)

**AS-IS:** On-device inference service for avian species classification using BirdNET's native TFLite model pipeline. Automatically analyzes indexed recordings, writes detections to the database, and extracts audio clips of detected bird calls.
**Target:** Taxonomy-enriched species metadata (i18n, IUCN status), spectrogram overlays, custom model fine-tuning (v1.0.0+).

---

## 1. The Problem / The Gap

*   **Audible Analysis:** Identifying bird species from audio recordings requires automated classification — manual review of 24/7 field recordings is infeasible.
*   **Model Complexity:** BirdNET-Analyzer is a complex pipeline of TFLite models and custom logic, requiring a dedicated service to encapsulate the inference workflow and memory management.
*   **Resource Constraints:** Running ML inference on an RPi 5 demands explicit memory management (`gc.collect()`, executor-bound I/O) to prevent OOM conditions during continuous operation.

## 2. User Benefit

*   **Biodiversity Insight:** Automatic species lists per recording session, location, and time period — no manual listening required. (US-B01)
*   **Location Awareness:** Species detection is restricted to regionally and seasonally occurring species using the BirdNET meta-model and station coordinates. (US-B03)
*   **Tunable Accuracy:** Confidence threshold, sensitivity, overlap, and processing order are adjustable via database configuration. (US-B04, US-B07)
*   **Backlog Processing:** The worker autonomously processes accumulated recordings when enabled or re-enabled. (US-B06)
*   **Audio Evidence:** Each detection includes an extracted WAV clip with configurable padding for manual verification. (US-B01)

---

## 3. Core Responsibilities

### Inputs

*   **Audio Files:** Processed recordings (48 kHz) from the Recorder workspace (mounted **read-only**, Consumer Principle, ADR-0009).
*   **Database Queue:** Polls for unanalyzed files via the Worker Pull Pattern (ADR-0018).
*   **Database Configuration:** Reads runtime tuning parameters via Snapshot Refresh (ADR-0031).

### Processing

*   **Native Inference:** Loads the BirdNET TFLite model once at startup via `ai-edge-litert` (resident in memory). Splits processed recordings into 3-second audio windows and runs inference per chunk on a background thread. No CLI subprocess, no CSV intermediaries, no `birdnetlib` wrapper (ADR-0027).
*   **Location Filtering:** Runs the BirdNET meta-model with station coordinates + week-of-year to generate a species mask. Species outside the geographic/seasonal range are excluded from results.
*   **Clip Extraction:** Extracts WAV audio clips for each detection (detection time range ± configurable padding).

### Outputs

*   **Database Rows:** Inserts classification results into the database.
*   **Audio Clips:** Saves WAV clips to the BirdNET workspace (`clips/`), linking the relative file path to the detection record.
*   **Redis Heartbeats:** Fire-and-forget heartbeats (ADR-0019). Includes backlog size, total analyzed, total detections, and avg inference time in the heartbeat metadata.

---

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                                           |
| ---------------- | -------------------------------------------------------------------------------------- |
| **Immutable**    | Yes — config at startup + Snapshot Refresh per cycle, restart to reconfigure (ADR-0019) |
| **DB Access**    | Yes — reads `recordings` + `system_config`, writes `detections`                        |
| **Concurrency**  | Queue Worker — blocking inference delegated to `run_in_executor` thread                |
| **State**        | Stateless (clips are output artifacts, not internal state)                             |
| **Privileges**   | Rootless                                                                               |
| **Resources**    | High — CPU-intensive inference (TFLite Lite variant for RPi)                           |
| **QoS Priority** | `oom_score_adj=+500` — **Expendable**. OOM Killer targets this before Recorder.        |

> [!IMPORTANT]
> BirdNET is an **expendable** analysis worker. If the system is under memory pressure, the OOM Killer will terminate BirdNET before the Recorder (`oom_score_adj=-999`). This is by design — Data Capture Integrity is paramount (ADR-0020).

---

## 5. Configuration & Environment

### Infrastructure (.env / Container Variables)
*(Only list variables/mounts required before the container starts. Never list dynamic DB tuning parameters here).*

| Variable / Mount                               | Description                             | Default / Example   |
| ---------------------------------------------- | --------------------------------------- | ------------------- |
| `SILVASONIC_INSTANCE_ID`                       | Service instance identifier             | `birdnet`           |
| `SILVASONIC_WORKSPACE_DIR`                     | BirdNET workspace (clips, read-write)   | `/data/birdnet`     |
| `SILVASONIC_RECORDINGS_DIR`                    | Processed recordings (read-only mount)  | `/data/recorder`    |
| `SILVASONIC_REDIS_URL`                         | Redis connection string                 | `redis://…:6379/0`  |
| `SILVASONIC_BIRDNET_MODEL_DIR`                 | Model directory (TFLite + labels)       | `/app/models`       |
| `${WORKSPACE}/recorder:ro,z`                   | All recorder workspaces (read-only)     | —                   |
| `${WORKSPACE}/birdnet:z`                       | BirdNET workspace (clips, read-write)   | —                   |

### Application Settings (Dynamic)

> [!NOTE]
> Managed centrally via DB / Pydantic. See [Configuration Architecture](../../docs/adr/0023-configuration-management.md) for factory defaults and developer overrides.

---

## 6. Technology Stack

*   **ML Runtime:** `ai-edge-litert` (Google's TFLite successor) — mandatory for resource-constrained RPi 5 deployment.
*   **Audio I/O:** `soundfile` (WAV read/write, clip extraction), `numpy` (spectrogram processing, 3-second chunk splitting).
*   **Python:** `silvasonic-core` (core lifecycle infrastructure, health monitoring, two-phase logging, heartbeats), `structlog` (JSON logging).
*   **Models:** BirdNET Global 6K V2.4 — FP32 classifier (~30 MB) + FP16 meta-model (~10 MB) + labels file. Models are downloaded at container build time from the `birdnetlib` PyPI wheel.
*   **Base Image:** `python:3.13-slim-bookworm` (Containerfile).

---

## 7. Out of Scope

*   **Does NOT** record audio (Recorder's job).
*   **Does NOT** classify bats (BatDetect's job — planned).
*   **Does NOT** persist raw recordings or manage file lifecycle (Processor's job).
*   **Does NOT** manage its own container lifecycle (Controller's job).
*   **Does NOT** compress or upload files (Processor Cloud-Sync-Worker's job).
*   **Does NOT** provide a UI (Web-Interface's job — v0.9.0).

---

## 8. Implementation Details (Domain Specific)

### Worker Pull Pattern

BirdNET implements the Worker Pull Orchestration pattern (ADR-0018):
1. Polls the database for files that have not yet been analyzed by this service.
2. Claims a single recording atomically.
3. After successful inference, marks the recording as done.
4. On failure, securely logs the error state to prevent infinite retry loops.

### Workspace & Path Structure

**Container view** (`/data/birdnet` — own workspace, RW):
```
/data/birdnet/
└── clips/
    └── {recording_id}_{start_ms}_{end_ms}_{label}.wav
```

**Recorder view** (`/data/recorder` — read-only mount):
```
/data/recorder/
└── {workspace_dir}/
    └── data/processed/
        └── *.wav                  # Input for inference
```

### Snapshot Refresh (ADR-0031)

BirdNET uses the Snapshot Refresh pattern to dynamically react to configuration changes without requiring a full container restart:
- Reads configuration values every poll cycle.
- If latitude/longitude changed, the species mask is recomputed from the meta-model.
- Tuning parameters (threshold, sensitivity, overlap) take effect on the next recording.

### Two-Phase Logging

BirdNET uses the Two-Phase Logging pattern (ADR-0030):
- **Startup Phase:** Verbose per-recording log output for debugging.
- **Steady State:** Periodic summary logs with delta counters (analyzed, detections, errors) to prevent log spam.

### Soft-Fail Resilience (ADR-0030)

Database outages do not crash the worker. Transient DB errors are caught, logged, and retried after a configurable interval. Health status is degraded to `database_unavailable` until reconnection.

---

## 9. References

- [ADR-0009: Zero-Trust Data Sharing](../../docs/adr/0009-zero-trust-data-sharing.md) — Consumer Principle (read-only mounts)
- [ADR-0018: Worker Pull Orchestration](../../docs/adr/0018-worker-pull-orchestration.md) — DB-based work claiming
- [ADR-0019: Unified Service Infrastructure](../../docs/adr/0019-unified-service-infrastructure.md) — SilvaService lifecycle, heartbeats
- [ADR-0020: Resource Limits & QoS](../../docs/adr/0020-resource-limits-qos.md) — `oom_score_adj=+500` (expendable)
- [ADR-0023: Configuration Management](../../docs/adr/0023-configuration-management.md) — `system_config` JSONB blobs
- [ADR-0027: BirdNET Inference Engine](../../docs/adr/0027-birdnet-inference-engine.md) — Native TFLite, no CLI wrapper
- [ADR-0029: System Worker Orchestration](../../docs/adr/0029-system-worker-orchestration.md) — `managed_services` lifecycle toggle
- [ADR-0030: Database Runtime Resilience](../../docs/adr/0030-database-resilience.md) — Soft-Fail Loops
- [ADR-0031: Runtime Tuning via DB Snapshot Refresh](../../docs/adr/0031-runtime-tuning-snapshot-refresh.md) — Snapshot Refresh
- [Glossary](../../docs/glossary.md) — BirdNET, Worker Pull, Detection definitions
- [User Stories — BirdNET](../../docs/user_stories/birdnet.md) — US-B01 through US-B08
- [ROADMAP.md](../../ROADMAP.md) — v0.8.0 milestone
