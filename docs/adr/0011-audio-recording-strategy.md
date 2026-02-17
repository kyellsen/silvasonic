# 11. Audio Recording Strategy (Raw vs Processed)

Date: 2026-01-31

## Status

Proposed

> **NOTE:** References to `processor`, `uploader`, or `janitor` refer to future services (planned for v0.3.0+). Currently, only `recorder` and `controller` exist.

## Context

The system supports various hardware microphones with different native capabilities (e.g., Dodotronic Ultramic at 384kHz, standard USB mics at 48kHz). Previously, we used terminology like "High Res" and "Low Res" or hardcoded 384kHz/48kHz assumptions. This is brittle and does not scale to different hardware configurations.

We need a standardized way to handle audio streams to ensure downstream services (Analysis, Visualization, Upload) know exactly what to expect, regardless of the input hardware.

## Decision

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

## Consequences

*   **Downstream Compatibility**: Services like BirdNET can blindly consume the `processed` folder knowing it is always 48kHz, removing the need for internal resampling.
*   **Hardware Independence**: Replacing a 384kHz mic with a 96kHz mic requires no code changes in downstream consumers, as `processed` remains 48kHz, and `raw` is just handled as "the archival file".
*   **Database Schema**: The `recordings` table uses `file_raw` and `file_processed` columns.
*   **Filesystem**: The workspace directory structure uses `data/recordings/raw` and `data/recordings/processed` within each microphone folder (see [Filesystem Governance](../arch/filesystem_governance.md)).
