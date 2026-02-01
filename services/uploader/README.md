# Container: Uploader

> **Service Name:** `uploader`
> **Container Name:** `silvasonic-uploader`
> **Package Name:** `silvasonic-uploader`

## 1. The Problem / The Gap
*   **Data Exfiltration:** Data stored on NVMe is useless unless researchers can access it.
*   **Limited Connectivity:** Field devices might have intermittent LTE or slow Wi-Fi. Syncing needs to be robust, resumable, and bandwidth-aware.

## 2. User Benefit
*   **Automatic Backup:** Recordings appear in the cloud (Nextcloud/S3) automatically.
*   **Disk Management:** Successful upload allows the "Janitor" to eventually delete local copies to free up space.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **Database Queue**: Query `recordings WHERE uploaded=false`.
    *   **Filesystem**: Read `.wav` files.
*   **Processing**:
    *   **Compression**: (Optional) Compressing to FLAC before upload to save bandwidth.
    *   **Transfer**: Transmitting data via Rclone (supports S3, SFTP, Drive, etc.).
    *   **Verification**: ensuring checksums match.
*   **Outputs**:
    *   **Remote Storage**: Files on cloud.
    *   **Database**: Update `uploaded=true, uploaded_at=now`.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **Worker**. Single or Multi-threaded uploads.
*   **State**: **Stateless** (tracks progress in DB).
*   **Privileges**: **Rootless**.
*   **Resources**: Network I/O bound. CPU usage for Compression.

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `RCLONE_CONFIG`: Path or Content of config.
    *   `REMOTE_DESTINATION`: e.g. `my-s3:bucket/path`.
*   **Volumes**:
    *   `/mnt/data` (Read Only).
    *   `/config/rclone` (Config).
*   **Dependencies**:
    *   `rclone` (Binary).

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** delete local files (Processor/Janitor job).
*   **Does NOT** record audio (Recorder job).
*   **Does NOT** analyze or classify audio (BirdNET job).
*   **Does NOT** index files into the database (Processor job).
*   **Does NOT** serve files to the web interface (Gateway job).

## 7. Technology Stack
*   **Base Image**: `python:3.11-slim-bookworm` (Dockerfile).
*   **Key Libraries**:
    *   `rclone` (System Binary) - Installed in Dockerfile.
*   **Build System**: `uv` + `Dockerfile`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Rclone is the industry standard for cloud sync.
*   **Alternatives**: Boto3 (AWS only), Paramiko (SFTP only). Rclone supports 40+ backends.

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** None detected. (System dependency `rclone` is correctly installed).
