# silvasonic-birdnet

> **Status:** Implemented (since v0.8.0) · **Tier:** 2 (Application, Managed by Controller) · **Instances:** Single · **Port:** 9500
>
> 📋 **User Stories:** [birdnet.md](../../docs/user_stories/birdnet.md)

**AS-IS:** On-device inference service for avian species classification using BirdNET's native TFLite model pipeline. Automatically analyzes indexed recordings, writes detections to the database, and extracts audio clips of detected bird calls.
**Target:** Enriched species metadata (i18n, IUCN status), spectrogram overlays, custom model fine-tuning (v1.0.0+).

---

## 1. The Problem / The Gap

*   **Audible Analysis:** Identifying bird species from audio recordings requires automated classification — manual review of 24/7 field recordings is infeasible.
*   **Model Complexity:** BirdNET-Analyzer is a complex pipeline of TFLite models and custom logic, requiring a dedicated service to encapsulate the inference workflow and memory management.
*   **Resource Constraints:** Running ML inference on an RPi 5 demands explicit memory management (`gc.collect()`, executor-bound I/O) to prevent OOM conditions during continuous operation.

## 2. User Benefit

*   **Biodiversity Insight:** Automatic species lists per recording session, location, and time period — no manual listening required. (US-B01)
*   **Location Awareness:** Species detection is restricted to regionally and seasonally occurring species using the BirdNET meta-model and station coordinates. (US-B03)
*   **Tunable Accuracy:** Minimum confidence, sensitivity, overlap, and processing order are adjustable via database configuration. (US-B04, US-B07)
*   **Backlog Processing:** The worker autonomously processes accumulated recordings when enabled or re-enabled. (US-B06)
*   **Audio Evidence:** Each detection includes an extracted WAV clip with configurable padding for manual verification. (US-B01)

---

## 3. Core Responsibilities

### Inputs

*   **Audio Files:** Processed recordings (48 kHz) from the Recorder workspace, or the raw file of a raw-only microphone, which is 48 kHz by profile rule (ADR-0011). Mounted **read-only** (Consumer Principle, ADR-0009). BirdNET does not resample: a file at another rate is not analysed and its `analysis_state` entry becomes `skipped` with reason `sample_rate_unsupported`. The check reads the file itself, not `recordings.sample_rate_hz`, which holds the microphone's native rate.
*   **Database Queue:** Polls for unanalyzed files via the Worker Pull Pattern (ADR-0018).
*   **Database Configuration:** Reads the `birdnet` and `station` sections of the `settings` table via Snapshot Refresh (ADR-0031): `min_confidence`, `sensitivity`, `overlap_s`, `clip_padding_s`, `thread_count`, `processing_order`, and the station's `latitude`/`longitude`.

### Processing

*   **Native Inference:** Loads the BirdNET TFLite model once at startup via `ai-edge-litert` (resident in memory). Splits processed recordings into 3-second audio windows and runs inference per chunk on a background thread. When the windows do not divide the recording evenly, one extra window is aligned to its end, so every sample is analysed (a 10 s segment without overlap gets windows at 0, 3, 6 and 7 s). No CLI subprocess, no CSV intermediaries, no `birdnetlib` wrapper (ADR-0027).
*   **Segment Boundaries:** The Recorder splits audio into segments, which can cut a call in two. When the previous segment of the same microphone ends where the current one starts (within 1 s) and is still on disk, its last 1.5 s are prepended and one extra *seam window* spans the boundary. Its detections belong to the current recording and start up to 1.5 s before it. A gap (FFmpeg restart, device unplugged) or a deleted predecessor skips the seam window. Cost: one more inference per segment.
*   **Location Filtering:** Runs the BirdNET meta-model with station coordinates + week-of-year to generate a species mask. Species outside the geographic/seasonal range are excluded from results. The week (BirdNET's 48-week year, four per month) comes from each recording's own timestamp, so a backlog is filtered by the season it was recorded in; masks are cached per week and dropped when the location changes.
*   **Clip Extraction:** Extracts WAV audio clips for each detection (detection time range ± configurable padding).
*   **Species Enrichment (best effort):** The first time a species is detected, a description (English and German) and a picture are fetched from Wikipedia and stored with the species, so the station can show them offline afterwards. This is the only step that needs internet access; without it a species simply has no description or picture yet. Sound classes that are not species are skipped, and a lookup that failed or stayed incomplete is repeated after six hours at the earliest.
    *   **Only the scientific name leaves the station**, sent to Wikipedia and Wikimedia Commons; no audio, coordinates or station identity.
    *   **Attributable content only.** Each description is stored with its article URL and licence (CC BY-SA 4.0). A picture is taken only from Wikimedia Commons, and only with the author, licence and file page Commons reports for it; a language Wikipedia's own uploads (often non-free) are never used. Whoever shows a description or picture shows its attribution with it.
    *   **Plain text.** Descriptions are stored as text, never as HTML from outside.
    *   **No database lock during the lookup.** The species row is read in one short transaction and written in another; the network calls happen in between (ADR-0037).

### Outputs

*   **Database Rows:** Inserts classification results into the database.
*   **Audio Clips:** Saves WAV clips to the BirdNET workspace (`clips/`), linking the relative file path to the detection record.
*   **Species Pictures:** Saves one picture per species to the BirdNET workspace (`wiki/img/`), named after the species id and linked from the species record with its source page, author and licence.
*   **Redis Heartbeats:** Fire-and-forget heartbeats (ADR-0019). Includes backlog size, total analyzed, total detections, and avg inference time in the heartbeat metadata.

---

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                                           |
| ---------------- | -------------------------------------------------------------------------------------- |
| **Immutable**    | Yes — config at startup + Snapshot Refresh per cycle, restart to reconfigure (ADR-0019) |
| **DB Access**    | Yes — reads `recordings` + `settings`, writes `detections` + `species`                 |
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
*   **HTTP:** `httpx` (Wikipedia lookups of the species enrichment).
*   **Python:** `silvasonic-core` (core lifecycle infrastructure, health monitoring, two-phase logging, heartbeats), `structlog` (JSON logging).
*   **Models:** BirdNET Global 6K V2.4 — FP32 classifier (~30 MB) + FP16 meta-model (~10 MB) + labels file. Models are downloaded at container build time from the `birdnetlib` PyPI wheel.
*   **Base Image:** `python:3.14-slim-bookworm` (Containerfile).

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
3. After successful inference, writes its `analysis_state` entry (`silvasonic.core.schemas.analysis.AnalysisState`): `{"state": "done", "reason": null, "finished_at": "<RFC 3339 UTC>", "detection_count": <n>}`.
4. On failure it writes `failed` with a short reason code (`file_missing`, `error`), or `skipped` with `sample_rate_unsupported`, so the recording is not claimed again. The error text goes to the log, not the database.

### Detections & Species

Each detection stores `analyzer = "birdnet"`, `started_at`/`ended_at`, the label as BirdNET reported it (`"Turdus merula_Eurasian Blackbird"`) and `species_id`, the slug of the scientific name (`turdus-merula`, ADR-0033). The first time a label is detected, BirdNET inserts a minimal `species` row (`ON CONFLICT DO NOTHING`): `id`, `analyzer`, `label`, `scientific_name`, `common_names: {"en": …}`, empty `descriptions`, and `category` — `bird`, or `other` when both halves of the label are identical (a sound class such as `Dog_Dog`). Existing rows are never changed. The insert runs in its own short transaction, apart from the detections.

### Workspace & Path Structure

**Container view** (`/data/birdnet` — own workspace, RW):
```
/data/birdnet/
├── clips/
│   └── {recording_id}_{start_ms}_{end_ms}_{label}.wav
└── wiki/img/
    └── {species_id}.jpg           # Picture from Wikipedia, one per species
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
- Tuning parameters (`min_confidence`, `sensitivity`, `overlap_s`) take effect on the next recording.

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
- [ADR-0023: Configuration Management](../../docs/adr/0023-configuration-management.md) — `settings` sections
- [ADR-0027: BirdNET Inference Engine](../../docs/adr/0027-birdnet-inference-engine.md) — Native TFLite, no CLI wrapper
- [ADR-0029: System Worker Orchestration](../../docs/adr/0029-system-worker-orchestration.md) — `modules` lifecycle toggle
- [ADR-0030: Database Runtime Resilience](../../docs/adr/0030-database-resilience.md) — Soft-Fail Loops
- [ADR-0031: Runtime Tuning via DB Snapshot Refresh](../../docs/adr/0031-runtime-tuning-snapshot-refresh.md) — Snapshot Refresh
- [Glossary](../../docs/glossary.md) — BirdNET, Worker Pull, Detection definitions
- [User Stories — BirdNET](../../docs/user_stories/birdnet.md) — US-B01 through US-B08
- [ROADMAP.md](../../ROADMAP.md) — v0.8.0 milestone
