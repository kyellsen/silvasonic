# ADR-0011: Audio Recording Strategy (Raw vs Processed)

> **Status:** Accepted • **Date:** 2026-01-31

> **NOTE:** References to `processor`, `uploader`, or `janitor` refer to future services (planned for v0.3.0+). Currently, only `recorder` and `controller` exist.

## 1. Context & Problem
The system supports various hardware microphones with different native capabilities (e.g., Dodotronic Ultramic at 384kHz, standard USB mics at 48kHz). Previously, we used terminology like "High Res" and "Low Res" or hardcoded 384kHz/48kHz assumptions. This is brittle and does not scale to different hardware configurations.

We need a standardized way to handle audio streams to ensure downstream services (Analysis, Visualization, Upload) know exactly what to expect, regardless of the input hardware.

## 2. Decision
**We chose:** A Dual Stream Architecture with standardized naming.

**Reasoning:**

1.  **Dual Stream Architecture**: The Recorder service MUST always produce two distinct streams:
    *   **Raw**: The native, bit-perfect capture from the hardware. Sample rate is variable (hardware-dependent).
    *   **Processed**: A standardized 48kHz stream derived from the raw input.

2.  **Naming Convention**:
    *   Streams and artifacts MUST be named `raw` and `processed`.
    *   We explicitly abandon names like `high`, `low`, `high_res`, `low_res` or specific bitrates (`384k`) in naming conventions (variables, directories, database columns).

3.  **Local Storage Format**:
    *   **Format**: `WAV` (linear PCM).
    *   **Motivation**: Minimal CPU overhead for writing; instant availability for local seeking/reading without decoding latency.
    *   **Structure** (see [Filesystem Governance](../arch/filesystem_governance.md) for full directory layout):
        *   `data/recordings/raw/*.wav`
        *   `data/recordings/processed/*.wav`

4.  **Cloud Storage Format**:
    *   **Format**: `FLAC` (Free Lossless Audio Codec).
    *   **Motivation**: Bandwidth efficiency. Uploading uncompressed WAVs is wasteful.
    *   **Policy**: The Uploader service converts `raw` artifacts to FLAC on-the-fly (or uses a buffer) before/during upload.

## 3. Options Considered
*   **Single Stream (Processed only):**
    *   *Rejected because*: Losing the raw, bit-perfect recording is unacceptable for scientific purposes. Hardware-native sample rates carry valuable high-frequency data (e.g., bat echolocation).
*   **Hardware-specific naming (`384k`, `48k`):**
    *   *Rejected because*: Brittle. Replacing a microphone with a different native sample rate would require changes across the entire codebase and database schema.

## 4. Consequences
*   **Positive:**
    *   **Downstream Compatibility**: Services like BirdNET can blindly consume the `processed` folder knowing it is always 48kHz, removing the need for internal resampling.
    *   **Hardware Independence**: Replacing a 384kHz mic with a 96kHz mic requires no code changes in downstream consumers, as `processed` remains 48kHz, and `raw` is just handled as "the archival file".
    *   **Database Schema**: The `recordings` table uses `file_raw` and `file_processed` columns.
    *   **Filesystem**: The workspace directory structure uses `data/recordings/raw` and `data/recordings/processed` within each microphone folder (see [Filesystem Governance](../arch/filesystem_governance.md)).
*   **Negative:**
    *   Requires double the storage for local recordings (raw + processed).
    *   CPU overhead for real-time resampling to produce the processed stream.

## 5. Future: Live Opus Stream (v0.9.0)

> **Status:** Planned

In v0.9.0, the Recorder will produce a **third output stream**, extending the Dual Stream Architecture to a **Triple Stream Architecture**:

| Stream        | Format    | Destination       | Purpose                         |
| ------------- | --------- | ----------------- | ------------------------------- |
| **Raw**       | WAV (PCM) | NVMe (local)      | Archival, scientific analysis   |
| **Processed** | WAV (PCM) | NVMe (local)      | BirdNET, BatDetect, consumption |
| **Live**      | Opus      | Icecast (network) | Real-time monitoring via Web-UI |

The Live stream is **best-effort** — if Icecast is unavailable, the Recorder continues writing Raw and Processed without interruption. **Data Capture Integrity applies:** the live stream must never compromise the recording pipeline.

Each Recorder pushes its Opus stream to a dedicated **mount point** on the Icecast server (e.g. `/mic-ultramic.opus`). The Web-Interface allows the user to select which microphone to listen to by switching the mount point URL.

## 6. Future: Retention Policy (v0.5.0 — The Janitor)

> **Status:** Planned  
> **Service:** `processor` (Tier 1, Critical)

To prevent storage exhaustion on the edge device, the `processor` service implements a centralized background cleanup task, colloquially called "The Janitor".

### Deletion Rules

- **Non-negotiable**: Files are typically only candidates for deletion if they meet high-level state criteria in TimescaleDB.
- **Criteria**: `uploaded == true` AND all required workers in `analysis_state` (JSONB) are marked as `true`.
- **Targeting**: Deletes the oldest 15s chunks first to free space iteratively.

### Survival Thresholds (3-Stage Rocket)

The Janitor operates in three escalating modes based on NVMe storage utilization:

#### 1. Housekeeping (>70% full)

- **Action**: Delete files where `uploaded=true` AND `analysis_state=complete`.
- **Log Level**: `INFO`.
- **Goal**: Regular storage rotation. No data loss, no analysis loss.

#### 2. Defensive (>80% full)

- **Action**: Delete files where `uploaded=true` (regardless of analysis).
- **Log Level**: `WARNING` ("Sacrificing local analysis for stability").
- **Goal**: Prevent "Disk Full" by removing locally redundant data. Remote copy exists in cloud storage.

#### 3. Panic Mode (>90% full)

- **Action**: Delete **OLDEST** files regardless of status.
- **Log Level**: `CRITICAL` ("DATA LOSS EVENT: Deleting non-uploaded data").
- **Fallback**: If Database is offline, fallback to filesystem `mtime` to clean up blindly.
- **Goal**: Survival. **The Recorder must never stop.**

### Design Rationale

This escalating policy enforces **Data Capture Integrity** as the paramount concern. In degraded states, the system will sacrifice local analysis completeness (Defensive Mode) or even remote backup guarantees (Panic Mode) to ensure the Recorder continues capturing audio. The device is designed to survive, even if it means losing non-uploaded historical data.

