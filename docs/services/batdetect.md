# BatDetect Service

> **Status:** planned - Not implemented · **Tier:** 2 · **Instances:** Single

> [!WARNING]
> **Docs-as-Code Trap:**
> This is a temporary **Planning Document**. When the service is implemented, do **NOT** copy this file into the source code as its `README.md`!
> Instead, strictly follow the rules in `docs/STRUCTURE.md` for Service READMEs (no paraphrased endpoints, no DB tables). Once implemented, this file must be replaced by an abstract link-stub.

**TO-BE:** On-device inference service for bat species classification using specialized ultrasonic ML models. Resource-intensive — **disabled by default**, only activated manually by the user.

---

## 1. The Problem / The Gap

*   **Ultrasonic Analysis:** Bat echolocation calls occupy the 20 kHz – 120 kHz range. General-purpose classifiers like BirdNET (targeting < 15 kHz) cannot detect them.
*   **Specialized Models:** Requires dedicated ML models (e.g., BatDetect2) trained on ultrasonic spectrograms.
*   **Specialized Hardware:** Only microphones with high sample rates (≥ 192 kHz, ideally 384 kHz+) can capture the ultrasonic frequency range needed for bat call detection. Standard microphones (48 kHz) cannot record bat echolocation calls.

## 2. User Benefit

*   **Biodiversity Insight:** Automatically identify bat species present in the acoustic environment — no manual spectrogram review required.
*   **Target Region:** Trained/tuned for **Central European bat species** (Germany, DACH region).
*   **Resource-Aware:** Disabled by default. Users with suitable hardware (ultrasonic microphone, ≥ 8 GB RAM) can opt in.

## 3. Core Responsibilities

### Inputs

*   **Audio Files:** High sample-rate **Raw** recordings (384 kHz+) from the Recorder workspace. Only recordings from microphones with ultrasonic capability are processed — standard 48 kHz recordings are skipped. Mounted **read-only** (Consumer Principle, ADR-0009).
*   **Database Queue:** Polls the `recordings` table for unanalyzed files via Worker Pull Pattern (`SELECT … FOR UPDATE SKIP LOCKED`, ADR-0018). Filters by `sample_rate >= 192000` to ensure only ultrasonic-capable recordings are processed.

### Processing

*   **Inference:** Runs BatDetect2 CNN models on ultrasonic spectrograms, producing species predictions with confidence scores.
*   **Selective Processing:** Only analyzes recordings within the configured activity window (default: dusk to dawn). Recordings outside this window are skipped.

### Outputs

*   **Database Rows:** Inserts classification results into the `detections` table (species label, confidence score, time range, common name).
*   **Audio Clips:** Extracts short WAV clips (detection range ± padding) from raw recordings and saves them to the BatDetect workspace (`batdetect/clips/`). The relative file path is stored in `detections.clip_path`.
*   **Redis Events:** Publishes detection notifications (best-effort, fire-and-forget).

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                                  |
| ---------------- | ----------------------------------------------------------------------------- |
| **Immutable**    | Yes — config at startup, restart to reconfigure (ADR-0019)                    |
| **DB Access**    | Yes — reads `recordings`, writes `detections`                                 |
| **Concurrency**  | Queue Worker — processing is slower than real-time on RPi                     |
| **State**        | Stateless                                                                     |
| **Privileges**   | Rootless                                                                      |
| **Resources**    | **Very High** — PyTorch inference requires ≥ 600 MB RAM, significant CPU load |
| **QoS Priority** | `oom_score_adj=+500` — expendable; recording takes priority                   |
| **Default**      | **Disabled** — must be manually activated by the user                         |

> [!CAUTION]
> BatDetect is the **most resource-intensive** analysis worker in the Silvasonic stack. PyTorch runtime alone requires ~500 MB RAM, with inference peaks reaching 600–900 MB. **Minimum recommended system RAM: 8 GB.** On 4 GB systems, enabling BatDetect alongside BirdNET may trigger the OOM Killer.

> [!IMPORTANT]
> BatDetect is an **expendable** analysis worker. If the system is under memory pressure, the OOM Killer will target BatDetect before the Recorder (`oom_score_adj=-999`). This is by design — Data Capture Integrity is paramount.

## 5. Configuration & Environment

| Variable / Mount                   | Description                          | Default / Example |
| ---------------------------------- | ------------------------------------ | ----------------- |
| `SILVASONIC_BATDETECT_PORT`        | Health endpoint port                 | `9500`            |
| `${SILVASONIC_WORKSPACE_PATH}/recorder:ro,z` | Recorder workspace (read-only mount) | —                 |
| `${SILVASONIC_WORKSPACE_PATH}/batdetect:z` | BatDetect workspace (clips, read-write) | —              |
| `POSTGRES_HOST`, `SILVASONIC_DB_*` | Database connection                  | via `.env`        |

### Dynamic Configuration (Database)

Runtime-tunable settings stored in the `system_config` table under key `batdetect` (ADR-0023). As an **Immutable Container** (ADR-0019), BatDetect reads these settings *once* on startup. The container lifecycle toggle (`enabled`) is managed via the `managed_services` table (ADR-0029), not via `system_config`.

| Setting                | Default  | Description                                                  |
| :--------------------- | :------- | :----------------------------------------------------------- |
| `confidence_threshold` | `0.25`   | Minimum confidence for species detection                     |
| `min_sample_rate`      | `192000` | Minimum recording sample rate to process (Hz)                |
| `schedule_start_hour`  | `19`     | Hour (local time) when analysis window begins (dusk)         |
| `schedule_end_hour`    | `7`      | Hour (local time) when analysis window ends (dawn)           |
| `schedule_enabled`     | `true`   | If true, only recordings within the time window are analyzed |

**Update Mechanism (State Reconciliation):**
1. User changes settings in Web UI.
2. Frontend updates `system_config` in DB and publishes a `silvasonic:nudge` event to the Controller (per ADR-0017).
3. The Controller restarts the BatDetect container.
4. BatDetect reads the new settings from the database upon startup.

## 6. Technology Stack

*   **ML Model:** BatDetect2 ([github.com/macaodha/batdetect2](https://github.com/macaodha/batdetect2)) — CNN-based bat call detection and species classification, trained on European full-spectrum ultrasonic recordings. Python 3.13, PyTorch 2 compatible. Finetuning for Central European species planned.
*   **Runtime:** PyTorch 2 — full framework required (no TFLite variant available). This is the primary reason for the high resource requirements.
*   **Audio:** `soundfile`, `numpy` (ultrasonic spectrogram generation)

> [!NOTE]
> **Why PyTorch and not TFLite?** Unlike BirdNET (which provides an official TFLite model), BatDetect2 is built exclusively on PyTorch. There is no lightweight alternative with comparable accuracy for European bat species. The trade-off is accepted: higher resource usage in exchange for state-of-the-art ultrasonic classification.

## 7. Open Questions & Future Ideas

*   Finetuning BatDetect2 on Central European (DACH region) bat call datasets for improved accuracy
*   GPU acceleration on RPi 5 — is the Hailo AI Hat useful for BatDetect inference?
*   Evaluate ONNX export of BatDetect2 model to reduce PyTorch runtime overhead
*   Confidence threshold tuning per species group
*   Post-MVP: spectrogram visualization with call annotations in the Web-Interface
*   Evaluate emerging alternatives: BSG-BATS (21 EU species), Bat2Web (lightweight CNN)

## 8. Out of Scope

*   **Does NOT** record audio (Recorder's job).
*   **Does NOT** classify birds (BirdNET's job).
*   **Does NOT** persist raw data (Database's job).
*   **Does NOT** manage its own container lifecycle (Controller's job).
*   **Does NOT** compress or upload files (Uploader's job).
*   **Does NOT** analyze standard 48 kHz recordings (only ultrasonic-capable data).

## 9. References

*   [Database Schema (DDL)](https://github.com/kyellsen/silvasonic/blob/main/services/database/init/01-init-schema.sql) — authoritative definition of the `detections` table schema.
*   [ADR-0009](../adr/0009-zero-trust-data-sharing.md) — Consumer Principle (read-only mounts)
*   [ADR-0018](../adr/0018-worker-pull-orchestration.md) — Worker Pull Orchestration
*   [ADR-0019](../adr/0019-unified-service-infrastructure.md) — Immutable Container, SilvaService lifecycle
*   [ADR-0020](../adr/0020-resource-limits-qos.md) — Resource Limits & QoS
*   [ADR-0023](../adr/0023-configuration-management.md) — Configuration Management
*   [Glossary: BatDetect](../glossary.md) — canonical definition
*   [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md) — milestone (v1.3.0)
