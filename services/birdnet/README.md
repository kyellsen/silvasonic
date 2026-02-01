# Container: BirdNET

> **Service Name:** `birdnet`
> **Container Name:** `silvasonic-birdnet`
> **Package Name:** `silvasonic-birdnet`

## 1. The Problem / The Gap
*   **Audible Analysis:** Identifying bird species from audio recordings.
*   **Model Complexity:** BirdNET-Analyzer is a complex connection of TFLite models and custom logic.

## 2. User Benefit
*   **Biodiversity Insight:** Auto-generated species lists.
*   **Education:** "Shazam for Birds" functionality.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **Audio Files**: Processed (48kHz) recordings from `/mnt/data/recordings/processed`.
    *   **Database Queue**: `recordings` waiting for classification.
*   **Processing**:
    *   **Inference**: Running BirdNET-Analyzer.
*   **Outputs**:
    *   **Database Rows**: Inserts into `detections` (Species, Confidence, Time).
    *   **Redis Events**: `silvasonic.detection.bird`.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **Queue Worker**.
*   **State**: **Stateless**.
*   **Privileges**: **Rootless**.
*   **Resources**: **High**. CPU intensive (Lite version recommended for Pi).

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `LATITUDE`, `LONGITUDE` (Improves BirdNET accuracy).
    *   `CONFIDENCE_THRESHOLD`.
*   **Volumes**:
    *   `/mnt/data` (Read Only).
*   **Dependencies**:
    *   `birdnet-analyzer` (Python Pkg) or `tflite-runtime`.

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** record audio.
*   **Does NOT** classify bats (BatDetect job).
*   **Does NOT** store data (Database job).

## 7. Technology Stack
*   **Base Image**: `python:3.11-slim-bookworm` (Dockerfile).
*   **Key Libraries**:
    *   None currently installed (Scaffolding).
*   **Build System**: `uv` + `Dockerfile`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Decoupled worker pattern.
*   **Alternatives**: AudioMoth-Live (different hardware).

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** **SCAFFOLDING ONLY**: No ML libraries installed yet.
