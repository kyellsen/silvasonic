# Container: BatDetect

> **Service Name:** `batdetect`
> **Container Name:** `silvasonic-batdetect`
> **Package Name:** `silvasonic-batdetect`

## 1. The Problem / The Gap
*   **Ultrasonic Analysis:** Bat calls are in the 20kHz-120kHz range. Processors like BirdNET (aimed at <15kHz) cannot detect them.
*   **Specialized Models:** Requires specialized ML models (e.g., BatDetect2, SoniBat) trained on ultrasonic spectrograms.

## 2. User Benefit
*   **Biodiversity Insight:** Identify bat species present in the environment.
*   **Real-time Trigger:** Can trigger high-speed recording modes if a bat is detected (future).

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **Audio Files**: High sample-rate recordings (384kHz+) from `/mnt/data/recordings`.
    *   **Database Queue**: `recordings` waiting for classification.
*   **Processing**:
    *   **Inference**: Running BatDetect CNN models.
*   **Outputs**:
    *   **Database Rows**: Inserts into `detections` (Species, Confidence, Time).
    *   **Redis Events**: `silvasonic.detection.bat`.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **Queue Worker**. Processing is slower than real-time on Pi, so it must work asynchronously.
*   **State**: **Stateless**.
*   **Privileges**: **Rootless**.
*   **Resources**: **High**. CPU/GPU intensive.

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `MODEL_PATH`: Path to `.tflite` or `.pth` model.
    *   `CONFIDENCE_THRESHOLD`: e.g. 0.8.
*   **Volumes**:
    *   `/mnt/data` (Read Only).
    *   `/models` (Read Only).
*   **Dependencies**:
    *   ML Framework (Torch/Tensorflow Lite).

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** record audio.
*   **Does NOT** classify birds (BirdNET job).
*   **Does NOT** store data (Database job).

## 7. Technology Stack
*   **Base Image**: `python:3.11-slim-bookworm` (Dockerfile).
*   **Key Libraries**:
    *   None currently installed (Scaffolding).
*   **Build System**: `uv` + `Dockerfile`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Dedicated container allows isolation of heavy ML dependencies (huge Docker images).
*   **Alternatives**: Running on same container as Recorder would cause buffer overruns due to CPU usage.

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** **SCAFFOLDING ONLY**: No ML libraries installed yet.
