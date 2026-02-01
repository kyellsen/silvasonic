# Container: Processor

> **Service Name:** `processor`
> **Container Name:** `silvasonic-processor`
> **Package Name:** `silvasonic-processor`

## 1. The Problem / The Gap
*   **Data Visibility:** Raw files on disk are not queryable. We need a system to scan, catalog, and index recordings into the Database to make them searchable by time, sensor, and duration.
*   **Visualization:** Generating spectrograms is CPU-intensive and shouldn't block the `recorder` or the `web-interface`. Ideally, it's done eagerly in the background.
*   **Storage Health:** Disks fill up. A dedicated process is needed to enforce retention policies (the "Janitor") without risking deleting active files.

## 2. User Benefit
*   **Instant Search:** Recordings appear in the UI timeline shortly after creation.
*   **Visual context:** Spectrograms are pre-generated, allowing instant scrubbing in the UI without browser-side processing lag.
*   **Disk Safety:** The system automatically deletes the oldest synced data when disk space is low, preventing the "Disk Full -> Crash" scenario.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **Filesystem Events**: Monitors `/mnt/data/recordings/` for new `.wav` files (via Polling or `inotify`).
    *   **Database Config**: Retention polices and storage quotas.
*   **Processing**:
    *   **Indexing**: Parses filenames (`timestamp`, `sensor`), calculates duration (header read), and inserts/updates rows in the `recordings` table.
    *   **Spectrogram Generation**: Creates `.png` visual representations (mel-spectrograms) for the UI.
    *   **Janitor / Retention**: Periodically checks disk usage. If Usage > Threshold (e.g., 90%), deletes oldest `uploaded=True` recordings.
*   **Outputs**:
    *   **Database Rows**: Inserts into `recordings`.
    *   **Redis Events**: Publishes `silvasonic.audit` events ("New Recording Indexed").
    *   **Files**: `.png` images in `/mnt/data/spectrograms/`.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **Batched / Worker**. Can run parallel threads for spectrogram generation, but DB writes should be batched to reduce lock contention.
*   **State**: **Stateless Logic** but heavily dependent on **Stateful Storage** (DB + FS).
*   **Privileges**: **Rootless**. Must have Read/Write access to `/mnt/data` (Group `pi`).
*   **Resources**: High CPU usage during spectrogram generation (should be nice/throttled if competing with Recorder).

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `DB_DSN`: Postgres Connection String.
    *   `RETENTION_GB`: Max storage usage target.
*   **Volumes**:
    *   `/mnt/data` (Read/Write): For accessing recordings and writing spectrograms.
*   **Dependencies**:
    *   `libsndfile` (Validation).
    *   `ffmpeg` (Optional, for format conversion if needed).

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** record audio (Recorder job).
*   **Does NOT** classify species (BirdNET job).
*   **Does NOT** upload files (Uploader job).
*   **Does NOT** serve the HTTP API (Gateway/FastAPI job) - it effectively "pre-renders" assets for them.
*   **Does NOT** manage service lifecycles (Controller job).

## 7. Technology Stack
*   **Base Image**: `python:3.11` (Data Science variants often used, but Standard Slim preferred if deps allow).
*   **Key Libraries**:
    *   `watchdog` (Filesystem Events).
    *   `sqlalchemy` / `asyncpg` (DB Access).
    *   `matplotlib` or `librosa` (Spectrograms).
    *   `pillow` (Image handling).
*   **Build System**: `uv` + `hatchling`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Separation of Concerns: Indexing is decoupled from Capture. Using `inotify` vs Polling needs careful tuning for reliability (Polling fallback recommended per architecture).
*   **Alternatives**: Could be integrated into the Recorder, but that risks blocking the capture loop. Current Microservice approach is safer.

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** None detected. (Service currently in Design/Scaffold phase).
