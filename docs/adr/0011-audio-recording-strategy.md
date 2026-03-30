# ADR-0011: Audio Recording Strategy (Raw vs Processed)

> **Status:** Accepted (amended 2026-03-30) • **Date:** 2026-01-31

> **NOTE:** The `processor` (v0.5.0) and `uploader` (v0.6.0) are implemented. References to `birdnet`, `batdetect`, or `weather` refer to planned services.

## 1. Context & Problem
The system supports various hardware microphones with different native capabilities (e.g., Dodotronic Ultramic at 384kHz, standard USB mics at 48kHz). Previously, we used terminology like "High Res" and "Low Res" or hardcoded 384kHz/48kHz assumptions. This is brittle and does not scale to different hardware configurations.

We need a standardized way to handle audio streams to ensure downstream services (Analysis, Visualization, Upload) know exactly what to expect, regardless of the input hardware.

## 2. Decision
**We chose:** A Dual Stream Architecture with standardized naming.

**Reasoning:**

1.  **Logical Dual Stream Architecture**: The Recorder service MUST always produce the **Raw** stream. The **Processed** stream is produced when the device's microphone profile sets `processed_enabled: true` (the default). Profiles for microphones whose native sample rate matches the target (48 kHz) set `processed_enabled: false` — no resampling is needed, so `data/raw` IS the analysis-ready stream.
    *   **Raw**: The native, bit-perfect capture from the hardware. Sample rate is variable (hardware-dependent). **Always present.**
    *   **Processed**: A standardized 48 kHz stream derived from the raw input. **Present only when `processed_enabled: true`.**

2.  **Naming Convention**:
    *   Streams and artifacts MUST be named `raw` and `processed`.
    *   We explicitly abandon names like `high`, `low`, `high_res`, `low_res` or specific bitrates (`384k`) in naming conventions (variables, directories, database columns).
    *   **Filename Format**: All files MUST adhere to the v0.6.0 collision-proof format: `YYYY-MM-DDTHH-MM-SSZ_{duration}s_{run_id}_{seq:08d}.wav`. Pre-v0.6.0 legacy fallback formats are strictly forbidden.

3.  **Local Storage Format**:
    *   **Format**: `WAV` (linear PCM).
    *   **Motivation**: Minimal CPU overhead for writing; instant availability for local seeking/reading without decoding latency.
    *   **Structure** (see [Filesystem Governance](../arch/filesystem_governance.md) for full directory layout):
        *   `data/raw/YYYY-MM-DDTHH-MM-SSZ_{duration}s_{run_id}_{seq}.wav`
        *   `data/processed/YYYY-MM-DDTHH-MM-SSZ_{duration}s_{run_id}_{seq}.wav`

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
    *   **Downstream Compatibility**: Services like BirdNET consume the preferred audio via `COALESCE(file_processed, file_raw)`, always receiving 48 kHz data without internal resampling.
    *   **Hardware Independence**: Replacing a 384 kHz mic with a 96 kHz mic requires no code changes in downstream consumers, as `processed` remains 48 kHz, and `raw` is just handled as "the archival file".
    *   **Database Schema**: The `recordings` table uses `file_raw` (NOT NULL) and `file_processed` (NULLABLE) columns. Raw-only devices insert `file_processed = NULL` and `filesize_processed = 0`.
    *   **Filesystem**: The workspace directory structure uses `data/raw` and optionally `data/processed` within each microphone folder (see [Filesystem Governance](../arch/filesystem_governance.md)).
    *   **Cross-Service Contract**: The Controller stores `devices.workspace_name` during enrollment, which the Processor Indexer uses to resolve filesystem paths to the device's stable identity (`devices.name`).
*   **Negative:**
    *   Requires up to double the storage for local recordings when both streams are active (raw + processed).
    *   CPU overhead for real-time resampling to produce the processed stream (handled by FFmpeg, see ADR-0024).

## 5. Future: Live Opus Stream (v1.1.0)

> **Status:** Planned

In v1.1.0, the Recorder will produce a **third output stream**, extending the Dual Stream Architecture to a **Triple Stream Architecture**:

| Stream        | Format    | Destination       | Purpose                         |
| ------------- | --------- | ----------------- | ------------------------------- |
| **Raw**       | WAV (PCM) | NVMe (local)      | Archival, scientific analysis   |
| **Processed** | WAV (PCM) | NVMe (local)      | BirdNET, BatDetect, consumption |
| **Live**      | Opus      | Icecast (network) | Real-time monitoring via Web-UI |

The Live stream is **best-effort** — if Icecast is unavailable, the Recorder continues writing Raw and Processed without interruption. **Data Capture Integrity applies:** the live stream must never compromise the recording pipeline.

Each Recorder pushes its Opus stream to a dedicated **mount point** on the Icecast server (e.g. `/mic-ultramic.opus`). The Web-Interface allows the user to select which microphone to listen to by switching the mount point URL.

## 6. Retention Policy (v0.5.0 — The Janitor)

> **Status:** Implemented (since v0.5.0)
> **Service:** `processor` (Tier 1, Critical)

To prevent storage exhaustion on the edge device (typical: 256 GB NVMe), the `processor` service implements a centralized background cleanup task, colloquially called "The Janitor".

### Design Decision

We have decided to enforce **Data Capture Integrity** via an escalating retention policy based on local disk utilization. As storage fills up, the policy progressively sacrifices first local analysis completeness, and eventually remote backup guarantees, to ensure the Recorder never faces a "Disk Full" scenario and never stops recording.

### Batch Size Limit

Deletions are limited to `janitor_batch_size` (default: **50**) files per cleanup cycle to prevent I/O storms and excessive database load. At 10-second segments, this corresponds to ~8 minutes of audio per batch.

### Uploader-Fallback (Pre-v0.6.0)

When no Uploader is configured (no active `storage_remotes` rows in the database), the `uploaded` condition in Housekeeping and Defensive modes is skipped. This prevents the Janitor from remaining idle until the Panic threshold is reached. The fallback is logged at `WARNING` level with the key `janitor.uploader_fallback_active`.
If Uploaders *are* configured, the `uploaded` condition is strictly interpreted as meaning the file has been successfully uploaded to **ALL currently active remotes**.

The exact implementation details, thresholds, and deletion rules are maintained authoritatively in the **[Processor Service Documentation](../services/processor.md)**.

## 7. Implementation: FFmpeg Audio Engine (v0.4.0)

> **Status:** Implemented (since v0.4.0)
> **See:** [ADR-0024](0024-ffmpeg-audio-engine.md) for the full architectural decision.

The Dual Stream output (Raw + Processed) is produced by a single **FFmpeg subprocess** managed by the Recorder service. FFmpeg handles ALSA capture, resampling, segmentation, and WAV encoding in native C code — the Python GIL never touches the audio path.

The Recorder's Python process manages FFmpeg's lifecycle and atomically promotes completed segments from `.buffer/` to `data/` via filesystem polling and `os.replace()`.

