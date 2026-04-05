# BirdNET Service

> **Status:** partial · **Tier:** 2 · **Instances:** Single

> [!WARNING]
> **Docs-as-Code Trap:**
> This is a temporary **Planning Document**. When the service is implemented, do **NOT** copy this file into the source code as its `README.md`!
> Instead, strictly follow the rules in `docs/STRUCTURE.md` for Service READMEs (no paraphrased endpoints, no DB tables). Once implemented, this file must be replaced by an abstract link-stub.

**TO-BE:** On-device inference service for avian species classification using a native TFLite model pipeline.

---

## 1. The Problem / The Gap

*   **Audible Analysis:** Identifying bird species from audio recordings requires automated classification — manual review of 24/7 recordings is infeasible.
*   **Model Complexity:** BirdNET-Analyzer is a complex pipeline of TFLite models and custom logic, requiring a dedicated service to encapsulate the inference workflow.

## 2. User Benefit

*   **Biodiversity Insight:** Auto-generated species lists per recording session, location, and time period.
*   **Education:** "Shazam for Birds" functionality — identify species from any captured audio segment.

## 3. Core Responsibilities

### Inputs

*   **Audio Files:** Processed recordings (48 kHz) from the Recorder workspace (`data/processed/`). Mounted **read-only** (Consumer Principle, ADR-0009).
*   **Database Queue:** Polls the `recordings` table for unanalyzed files via Worker Pull Pattern (`SELECT … FOR UPDATE SKIP LOCKED`, ADR-0018).

### Processing

*   **Inference:** Loads the BirdNET TFLite model once at startup via `tflite_runtime.Interpreter` (resident in memory for the container's lifetime). Splits processed recordings into 3-second audio windows using `soundfile`/`numpy` and runs inference per chunk. Detections are native Python objects — no CLI subprocess, no CSV intermediaries, no `birdnetlib` wrapper (see [Milestone v0.8.0](../development/milestones/milestone_0_8_0.md) for architectural rationale).

### Outputs

*   **Database Rows:** Inserts classification results into the `detections` table (species label, confidence score, time range, common name).
*   **Audio Clips:** Extracts short WAV clips (detection time range ± configurable padding) from processed recordings using `soundfile` and saves them to the BirdNET workspace (`birdnet/clips/`). The relative file path is stored in `detections.clip_path`.
*   **Redis Events:** Publishes detection notifications (best-effort, fire-and-forget).

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                 |
| ---------------- | ------------------------------------------------------------ |
| **Immutable**    | Yes — config at startup, restart to reconfigure (ADR-0019)   |
| **DB Access**    | Yes — reads `recordings`, writes `detections`                |
| **Concurrency**  | Queue Worker — processing is slower than real-time on RPi    |
| **State**        | Stateless                                                    |
| **Privileges**   | Rootless                                                     |
| **Resources**    | High — CPU-intensive inference (TFLite Lite variant for RPi) |
| **QoS Priority** | `oom_score_adj=+500` — expendable; recording takes priority  |

> [!IMPORTANT]
> BirdNET is an **expendable** analysis worker. If the system is under memory pressure, the OOM Killer will target BirdNET before the Recorder (`oom_score_adj=-999`). This is by design — Data Capture Integrity is paramount.

## 5. Configuration & Environment

| Variable / Mount                    | Description                            | Default / Example |
| ----------------------------------- | -------------------------------------- | ----------------- |
| `SILVASONIC_BIRDNET_PORT`           | Health endpoint port                   | `9500`            |
| `${SILVASONIC_WORKSPACE_PATH}/recorder:ro,z` | Processed recordings (read-only mount) | —                 |
| `${SILVASONIC_WORKSPACE_PATH}/birdnet:z` | BirdNET workspace (clips, read-write)  | —                 |
| `POSTGRES_HOST`, `SILVASONIC_DB_*`  | Database connection                    | via `.env`        |

### Dynamic Configuration (Database)

Runtime-tunable settings stored in the `system_config` table (ADR-0023). Following the Singleton-Worker State Convention (ADR-0029), BirdNET reads these settings *once* on startup, and the Controller uses the `enabled` field to orchestrate the container.

| Key       | Setting                | Default | Description                                          |
| --------- | ---------------------- | ------- | ---------------------------------------------------- |
| `birdnet` | `enabled`              | `True`  | Master Controller toggle for the container lifecycle |
| `system`  | `latitude`             | `53.55` | Station latitude — restricts species list to region  |
| `system`  | `longitude`            | `9.99`  | Station longitude — restricts species list to region |
| `birdnet` | `confidence_threshold` | `0.25`  | Minimum confidence for species detection             |
| `birdnet` | `clip_padding_seconds` | `3.0`   | Padding around detection window for clip extraction  |
| `birdnet` | `overlap`              | `0.0`   | Overlap between analysis windows (0.0–3.0 seconds)   |
| `birdnet` | `sensitivity`          | `1.0`   | Model sensitivity (0.5–1.5)                          |
| `birdnet` | `threads`              | `1`     | Number of inference threads                          |

**Update Mechanism (State Reconciliation):**
1. User changes settings in Web UI.
2. Frontend updates `system_config` in DB and publishes a `silvasonic:nudge` event to the Controller (per ADR-0017).
3. The Controller restarts the BirdNET container.
4. BirdNET reads the new settings from the database upon startup.

## 6. Technology Stack

*   **ML Model:** BirdNET TFLite model (~30 MB), loaded once at container startup via `tflite_runtime.Interpreter` (resident in memory for the container's lifetime). Oriented on BirdNET-Pi's native integration approach — no CLI subprocess, no `birdnetlib` wrapper.
*   **Runtime:** `tflite-runtime` — mandatory for resource-constrained RPi 5 deployment. Explicit memory management (`del audio_chunk`, `gc.collect()`) prevents leaks during long-running inference loops.
*   **Audio:** `soundfile` (WAV I/O, clip extraction), `numpy` (spectrogram processing, 3-second chunk splitting).

## 7. Open Questions & Future Ideas

*   Custom model fine-tuning with local species data.
*   Post-MVP: spectrogram + detection overlay visualization in the Web-Interface.

## 8. Out of Scope

*   **Does NOT** record audio (Recorder's job).
*   **Does NOT** classify bats (BatDetect's job).
*   **Does NOT** persist raw data (Database's job).
*   **Does NOT** manage its own container lifecycle (Controller's job).
*   **Does NOT** compress or upload files (Uploader's job).

## 9. References

*   [Database Schema (DDL)](https://github.com/kyellsen/silvasonic/blob/main/services/database/init/01-init-schema.sql) — authoritative definition of the `detections` table schema.
*   [ADR-0009](../adr/0009-zero-trust-data-sharing.md) — Consumer Principle (read-only mounts)
*   [ADR-0018](../adr/0018-worker-pull-orchestration.md) — Worker Pull Orchestration
*   [ADR-0019](../adr/0019-unified-service-infrastructure.md) — Immutable Container, SilvaService lifecycle
*   [ADR-0020](../adr/0020-resource-limits-qos.md) — Resource Limits & QoS
*   [ADR-0023](../adr/0023-configuration-management.md) — Configuration Management (latitude, confidence threshold)
*   [Glossary: BirdNET](../glossary.md) — canonical definition
*   [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md) — milestone (v0.8.0)
