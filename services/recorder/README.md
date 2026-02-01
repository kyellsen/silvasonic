# Container: Recorder

> **Service Name:** `recorder`
> **Container Name:** `silvasonic-recorder`
> **Package Name:** `silvasonic-recorder`

## 1. The Problem / The Gap
*   **Gapless Capture:** Bioacoustic monitoring requires 24/7 continuous recording without gaps. General-purpose OS schedulers or heavy analysis loads can cause buffer overruns and dropped frames in monolithic applications.
*   **Hardware Abstraction:** Managing multiple USB microphones with varying sample rates and drift requires a dedicated, resilient capture process separated from the analysis logic.

## 2. User Benefit
*   **No Data Loss:** Ensures that every second of the soundscape is captured, even if the analysis system (BirdNET) crashes or the CPU is under heavy load.
*   **High Fidelity:** Captures raw "Native" audio (preserving the sensor's maximum potential) while simultaneously creating a standardized "Processed" stream for analysis.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **ALSA Data Stream**: Direct PCM audio data from USB Microphones (via `sounddevice` / `pyaudio`).
    *   **Configuration**: Target sample rate, gain settings, and file duration (from `system_config` / Environment).
*   **Processing**:
    *   **Ring Buffering**: Buffers incoming audio frames in RAM to smooth out write latency.
    *   **Stream Splitting**:
        *   Path A: Writes strictly raw data (e.g., 384kHz) to `file_raw`.
        *   Path B: Resamples/Mixes down to 48kHz for `file_processed` (Standardized Analysis Format).
    *   **File Rotation**: Closes and rotates files at fixed intervals (e.g., 15s) based on strict time boundaries.
*   **Outputs**:
    *   **Files**: `.wav` files written to the NVMe buffer (`/mnt/data/recordings/{sensor_id}/`).
    *   **Atomic Moves**: Writes to `.tmp` first, then atomically renames to `.wav` to signal "Write Complete" to the Processor.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **Real-Time Priority**. This service must have the highest priority/CPU affinity to prevent buffer overruns (`input overflow`).
*   **State**: **Stateless**. It does not maintain a database or long-term state. Validates config on startup and runs until termination.
*   **Privileges**: **Rootless**. Must run as user `pi` (UID 1000) or equivalent to write files owned by the host user. Requires access to the `audio` group (ALSA).
*   **Resources**: Moderate Memory (Ring Buffer), Low-but-Consistent CPU. Time-sensitive.

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `MIC_NAME`: The logical name of the sensor (e.g., `front`, `back`, `UltraMic`).
    *   `ALSA_DEVICE_INDEX` or `ALSA_CARD_NAME`: Target hardware address.
    *   `SAMPLE_RATE`: Requested capture rate (Hz).
*   **Volumes**:
    *   `/mnt/data` (Mounted as `/data`): Target for writing recordings.
*   **Dependencies**:
    *   `alsa-lib` / `libasound2` (System).

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** analyze audio (BirdNET/BatDetect job).
*   **Does NOT** index files into the database (Processor job).
*   **Does NOT** upload files to the cloud (Uploader job).
*   **Does NOT** manage microphone connections/disconnections (Controller job).
*   **Does NOT** generate spectrograms (Processor job).

## 7. Technology Stack
*   **Base Image**: `python:3.11-slim` (or optimized Base).
*   **Key Libraries**:
    *   `sounddevice` or `pyaudio` (Capture).
    *   `soundfile` or `scipy.io.wavfile` (Write).
    *   `numpy` (Buffer management).
    *   `structlog` (Logging).
*   **Build System**: `uv` + `hatchling`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Complies with "No-Data-Loss" by decoupling Capture from Analysis. Adheres to Rootless mandate.
*   **Alternatives**: `arecord` (CLI) is simpler but offers less control over buffering and stream splitting (Raw + Processed simultaneous write).

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** None detected. (Service currently in Design/Scaffold phase).
