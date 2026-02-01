# Container: BatDetect

> **Service Name:** `batdetect`
> **Container Name:** `silvasonic-batdetect`
> **Package Name:** `silvasonic-batdetect`

## 1. The Problem / The Gap
*   **Ultrasonic Analysis:** Bats call at frequencies (20kHz-120kHz) mostly inaudible to humans and invisible to standard audio tools.
*   **Specialized Models:** BirdNET cannot detect bats. A specialized model trained on high-sample-rate spectrograms is required.

## 2. User Benefit
*   **Bat Monitoring:** Automated detection of bat activity.
*   **Heterodyne/Time-Expansion:** (Future) Converting ultrasonic audio to audible range for user review.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **Audio Files**: `file_raw` (High Sample Rate, e.g. 192kHz/384kHz).
*   **Processing**:
    *   **STFT**: Generating spectrograms compatible with the model.
    *   **Inference**: Running the detection CNN.
*   **Outputs**:
    *   **Detections**: DB INSERTs.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **CPU Bound**.
*   **State**: **Stateless**.
*   **Privileges**: **Rootless**.
*   **Resources**: High CPU.

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `DETECTION_THRESHOLD`.
*   **Volumes**:
    *   `/mnt/data` (Read Only).
*   **Dependencies**:
    *   `torch` / `tflite-runtime`.

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** record audio.
*   **Does NOT** classify birds (BirdNET job).
*   **Does NOT** process standard 48kHz audio streams.
*   **Does NOT** upload data (Uploader job).
*   **Does NOT** manage hardware sensors (Controller job).

## 7. Technology Stack
*   **Base Image**: `python:3.11-slim`.
*   **Key Libraries**:
    *   `batdetect` (or similar).
    *   `numpy`.
*   **Build System**: `uv`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Separation of specialized inference tasks.
*   **Alternatives**: n/a.

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** None detected.
