# Container: Recorder

> **Service Name:** `recorder`
> **Container Name:** `silvasonic-recorder`
> **Package Name:** `silvasonic-recorder`

## 1. The Problem / The Gap
*   **Hardware Abstraction:** Different microphones (USB, I2S) have different sample rates and quirks. We need a unified way to capture audio.
*   **Reliability:** Recording processes can hang or drift. We need a robust process manager that survives glitches.
*   **Multi-Purpose Audio:** We need high-res raw data for science, normalized data for ML inference, and **low-latency** compressed data for live listening—simultaneously.

## 2. User Benefit
*   **Plug & Play:** Works with most ALSA devices.
*   **Live Monitoring:** Listen to the microphone in real-time via Icecast (Opus stream) without stopping the scientific recording.
*   **Data Quality:** "Raw" files are untouched (24-bit), ensuring no data loss for analysis.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **Audio Hardware**: ALSA Devices (`hw:0,0` etc.) or `lavfi` (Synthetic Test Source).
    *   **Configuration**: `MicrophoneProfile` (YAML) defining sample rates, channels, gain.
*   **Processing**:
    *   **FFmpeg Pipeline**: Orchestrates a complex filter graph using `ffmpeg-python`.
    *   **Stream Splitting**:
        1.  **Raw**: Preserves original sample rate/bit-depth (pcm_s24le).
        2.  **Processed**: Resamples to 48kHz (pcm_s16le) for consistent ML input.
        3.  **Live (Opus)**: Encodes to Ogg/Opus (64k) and pushes to Icecast.
    *   **Watchdog**: Monitors the FFmpeg subprocess via `stderr` for errors/death.
*   **Outputs**:
    *   **Filesystem**: Segmented WAV files in `raw/` and `processed/` directories.
    *   **Icecast Stream**: Pushes directly to an Icecast server (url configurable).
    *   **Logs**: Structured JSON logs via `structlog`.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **Process-Based**. The main work happens in the FFmpeg subprocess. The Python wrapper is threaded (Watchdog).
*   **State**: **Critical**. Must manage file handles and ALSA locks carefully.
*   **Privileges**: **Hardware Access**. Requires access to `/dev/snd` (Device Mapping or `--device`).
*   **Dependencies**: Requires a running **Icecast Server** reachable via network.
*   **Resources**: CPU intensive during Opus encoding. Low Memory (monitored via `psutil`).

## 5. Configuration & Environment
*   **Environment Variables**:
    *   Calculated at runtime via `MicrophoneProfile`.
    *   **Icecast**: `ICECAST_HOST`, `ICECAST_PORT`, `ICECAST_USER`, `ICECAST_PASSWORD`, `ICECAST_MOUNT`.
*   **Volumes**:
    *   `${SILVASONIC_WORKSPACE_PATH}/recorder` -> Output directory for WAV files.
*   **Dependencies**:
    *   **System**: `ffmpeg`, `alsa-utils`.
    *   **Python**: `ffmpeg-python`, `silvasonic-core`.

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** analyze the audio (Processor job).
*   **Does NOT** upload files to the cloud (Uploader job).
*   **Does NOT** provide a UI (Web Interface job).
*   **Does NOT** store metadata in SQL (Database job, though it may send events via Redis).

## 7. Technology Stack
*   **Base Image**: `python:3.11-slim-bookworm`.
*   **Key Libraries**:
    *   `ffmpeg-python` (Wrapper).
    *   `structlog` (Logging).
*   **Build System**: `uv` (Fast Python Package Installer).

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Uses `ffmpeg-python` for graph construction, which is cleaner than raw shell strings. Watchdog ensures resilience.
*   **Alternatives**: Pure Python Audio (PyAudio/SoundDevice) is harder to split into 3 reliable streams (Raw/Proc/Live) without GIL issues or drift. FFmpeg is the battle-tested standard here.

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** None detected.
