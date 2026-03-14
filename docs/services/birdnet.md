# BirdNET Service

> **Status:** planned - Not implemented · **Tier:** 2 · **Instances:** Single

**TO-BE:** On-device inference service for avian species classification using the BirdNET-Analyzer framework.

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

*   **Inference:** Runs BirdNET-Analyzer on 3-second audio segments, producing species predictions with confidence scores.

### Outputs

*   **Database Rows:** Inserts classification results into the `detections` table (species label, confidence score, time range, common name).
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
| `${SILVASONIC_WORKSPACE_PATH}/recorder:ro` | Processed recordings (read-only mount) | —                 |
| `POSTGRES_HOST`, `SILVASONIC_DB_*`  | Database connection                    | via `.env`        |

### Dynamic Configuration (Database)

Runtime-tunable settings stored in the `system_config` table (ADR-0023). As an **Immutable Container** (ADR-0019), BirdNET reads these settings *once* on startup.

| Key       | Setting                | Default | Description                                          |
| --------- | ---------------------- | ------- | ---------------------------------------------------- |
| `system`  | `latitude`             | `53.55` | Station latitude — restricts species list to region  |
| `system`  | `longitude`            | `9.99`  | Station longitude — restricts species list to region |
| `birdnet` | `confidence_threshold` | `0.25`  | Minimum confidence for species detection             |

**Update Mechanism (State Reconciliation):**
1. User changes settings in Web UI.
2. Frontend updates `system_config` in DB and publishes a `silvasonic:nudge` event to the Controller (per ADR-0017).
3. The Controller restarts the BirdNET container.
4. BirdNET reads the new settings from the database upon startup.

## 6. Technology Stack

*   **ML Model:** BirdNET-Analyzer — TFLite-based avian species classifier.
*   **Runtime:** TensorFlow Lite (`tflite-runtime`). This is the official and mandatory requirement for deployment on resource-constrained Edge devices like the Raspberry Pi 5 to drastically reduce RAM and CPU overhead compared to full TensorFlow.
*   **Audio:** `soundfile`, `numpy` (spectrogram / segment extraction).

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

*   [Database Schema (DDL)](../../services/database/init/01-init-schema.sql) — authoritative definition of the `detections` table schema.
*   [ADR-0009](../adr/0009-zero-trust-data-sharing.md) — Consumer Principle (read-only mounts)
*   [ADR-0018](../adr/0018-worker-pull-orchestration.md) — Worker Pull Orchestration
*   [ADR-0019](../adr/0019-unified-service-infrastructure.md) — Immutable Container, SilvaService lifecycle
*   [ADR-0020](../adr/0020-resource-limits-qos.md) — Resource Limits & QoS
*   [ADR-0023](../adr/0023-configuration-management.md) — Configuration Management (latitude, confidence threshold)
*   [Glossary: BirdNET](../glossary.md) — canonical definition
*   [ROADMAP.md](../../ROADMAP.md) — milestone (v1.1.0)
