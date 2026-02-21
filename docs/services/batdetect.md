# BatDetect Service

> **Status:** Planned (v1.3.0) · **Tier:** 2 · **Instances:** Single

On-device inference service for bat species classification using specialized ultrasonic ML models.

---

## 1. The Problem / The Gap

*   **Ultrasonic Analysis:** Bat echolocation calls occupy the 20 kHz – 120 kHz range. General-purpose classifiers like BirdNET (targeting < 15 kHz) cannot detect them.
*   **Specialized Models:** Requires dedicated ML models (e.g., BatDetect2, SoniBat) trained on ultrasonic spectrograms.

## 2. User Benefit

*   **Biodiversity Insight:** Automatically identify bat species present in the acoustic environment — no manual spectrogram review required.

## 3. Core Responsibilities

### Inputs

*   **Audio Files:** High sample-rate recordings (384 kHz+) from the Recorder workspace. Mounted **read-only** (Consumer Principle, ADR-0009).
*   **Database Queue:** Polls the `recordings` table for unanalyzed files via Worker Pull Pattern (`SELECT … FOR UPDATE SKIP LOCKED`, ADR-0018).

### Processing

*   **Inference:** Runs BatDetect CNN models on ultrasonic spectrograms.

### Outputs

*   **Database Rows:** Inserts classification results into the `detections` table (species label, confidence score, time range, common name).
*   **Redis Events:** Publishes detection notifications (best-effort, fire-and-forget).

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                |
| ---------------- | ----------------------------------------------------------- |
| **Immutable**    | Yes — config at startup, restart to reconfigure (ADR-0019)  |
| **DB Access**    | Yes — reads `recordings`, writes `detections`               |
| **Concurrency**  | Queue Worker — processing is slower than real-time on RPi   |
| **State**        | Stateless                                                   |
| **Privileges**   | Rootless                                                    |
| **Resources**    | High — CPU-intensive inference                              |
| **QoS Priority** | `oom_score_adj=+500` — expendable; recording takes priority |

> [!IMPORTANT]
> BatDetect is an **expendable** analysis worker. If the system is under memory pressure, the OOM Killer will target BatDetect before the Recorder (`oom_score_adj=-999`). This is by design — Data Capture Integrity is paramount.

## 5. Configuration & Environment

| Variable / Mount                   | Description                          | Default / Example |
| ---------------------------------- | ------------------------------------ | ----------------- |
| `SILVASONIC_BATDETECT_PORT`        | Health endpoint port                 | `9500`            |
| `/mnt/data/recordings:ro`          | Recorder workspace (read-only mount) | —                 |
| `POSTGRES_HOST`, `SILVASONIC_DB_*` | Database connection                  | via `.env`        |

## 6. Technology Stack

*   **ML Model:** BatDetect2 (primary candidate) — CNN-based bat call detection and classification
*   **Audio:** `soundfile`, `numpy` (ultrasonic spectrogram generation)
*   **Inference:** PyTorch (BatDetect2 runtime)

## 7. Open Questions & Future Ideas

*   Which BatDetect2 model variant is best suited for European bat species?
*   GPU acceleration on RPi 5 — is the Hailo AI Hat useful for BatDetect inference?
*   Confidence threshold tuning per species group
*   Post-MVP: spectrogram visualization in the Web-Interface

## 8. Out of Scope

*   **Does NOT** record audio (Recorder's job).
*   **Does NOT** classify birds (BirdNET's job).
*   **Does NOT** persist raw data (Database's job).
*   **Does NOT** manage its own container lifecycle (Controller's job).
*   **Does NOT** compress or upload files (Uploader's job).

## 9. References

*   [ADR-0009](../adr/0009-zero-trust-data-sharing.md) — Consumer Principle (read-only mounts)
*   [ADR-0018](../adr/0018-worker-pull-orchestration.md) — Worker Pull Orchestration
*   [ADR-0019](../adr/0019-unified-service-infrastructure.md) — Immutable Container, SilvaService lifecycle
*   [ADR-0020](../adr/0020-resource-limits-qos.md) — Resource Limits & QoS
*   [Glossary: BatDetect](../glossary.md) — canonical definition
*   [VISION.md](../../VISION.md) — roadmap entry (v1.3.0)
