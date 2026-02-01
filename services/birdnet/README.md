# Container: BirdNET

> **Service Name:** `birdnet`
> **Container Name:** `silvasonic-birdnet`
> **Package Name:** `silvasonic-birdnet`

## 1. The Problem / The Gap
*   **Species Identification:** Raw audio is valuable, but hard to navigate. Researchers want to know "Which files contain a Thrush Nightingale?"
*   **Edge Computing:** Uploading terabytes of silence to the cloud for analysis is expensive. On-device inference filters the data.

## 2. User Benefit
*   **Instant Taxonomy:** See species lists in real-time.
*   **Targeted Uploads:** (Future) Configurable to only upload "Interesting" clips.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **Database Queue**: DB Polling (`recordings` where NOT analyzed).
    *   **Audio Files**: Reading `file_processed` (48kHz) from NVMe.
*   **Processing**:
    *   **Inference**: Running BirdNET TFLite model on audio chunks (3s).
    *   **Filtering**: Applying "Minimum Confidence" thresholds.
*   **Outputs**:
    *   **Detections**: Inserting rows `(time, species, confidence)` into DB.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **CPU Bound**. Single-process per container (Python GIL + TFLite). Scaled via multiple containers if needed.
*   **State**: **Stateless**.
*   **Privileges**: **Rootless**.
*   **Resources**: High CPU.

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `MIN_CONFIDENCE`: 0.0 - 1.0.
    *   `LATITUDE`/`LONGITUDE`: Required for BirdNET species prediction.
*   **Volumes**:
    *   `/mnt/data` (Read Only).
*   **Dependencies**:
    *   `tflite-runtime`.

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** record audio.
*   **Does NOT** generate spectrograms (Processor job).
*   **Does NOT** upload files (Uploader job).
*   **Does NOT** serve the user interface (Web Interface job).
*   **Does NOT** optimize or clean the database (Janitor job).

## 7. Technology Stack
*   **Base Image**: `python:3.11-slim` (Arm64 optimized).
*   **Key Libraries**:
    *   `birdnet-analyzer` (or custom wrapper).
    *   `tflite-runtime`.
    *   `numpy`.
    *   `librosa`.
*   **Build System**: `uv`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Using TFLite for Edge/Pi performance.
*   **Alternatives**: Full Tensorflow (Too heavy), Coral TPU (Possible future optimization).

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** None detected.
