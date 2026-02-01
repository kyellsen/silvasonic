# Container: Database

> **Service Name:** `database`
> **Container Name:** `silvasonic-database`
> **Package Name:** `silvasonic-database` (Docker Image Only)

## 1. The Problem / The Gap
*   **Time-Series Data:** Bioacoustic data creates millions of rows (recordings, detections, weather) ordered by time. Standard SQL databases degrade in performance with this volume.
*   **State Persistence:** Start/Stop/Config state needs to persist across reboots.

## 2. User Benefit
*   **Fast Queries:** TimescaleDB hypertables allow querying "Last 24 hours of Detections" in milliseconds, even with millions of rows.
*   **Data Integrity:** Transactional guarantees ensure metadata matches files on disk.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **SQL Queries**: INSERTs/SELECTs from all services (`recorder`, `processor`, `controller`).
*   **Processing**:
    *   **Storage**: Persisting relational data (System Config) and Time-Series data (Detections).
    *   **Compression**: (Future) Auto-compressing old chunks via TimescaleDB features.
*   **Outputs**:
    *   **Result Sets**: Data for the API/UI.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **High**. Optimized for many concurrent connections (via `asyncpg` in clients).
*   **State**: **Stateful**. The single most critical volume.
*   **Privileges**: **Rootless**. Runs as `postgres` user inside container, mapped to host sub-UIDs.
*   **Resources**: Configured for NVMe (`random_page_cost=1.1`, `synchronous_commit=off`).

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`.
    *   `PGDATA`: `/var/lib/postgresql/data`.
*   **Volumes**:
    *   `silvasonic-db-data` -> `/var/lib/postgresql/data`.
*   **Dependencies**:
    *   `timescaledb-ha` or standard `timescaledb` image.

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** store large binary blobs (WAV files are on FS, only paths stored here).
*   **Does NOT** expose ports to the internet (Internal Network only).
*   **Does NOT** manage application logic (it is a passive store).
*   **Does NOT** authenticate end-users (Gateway/API handles Auth).
*   **Does NOT** compress audio files (Uploader job).

## 7. Technology Stack
*   **Base Image**: `timescale/timescaledb:latest-pg16` (or current stable).
*   **Key Libraries**:
    *   PostgreSQL 16.
    *   TimescaleDB Extension.
*   **Build System**: Docker Hub Upstream.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Uses TimescaleDB for time-series efficiency.
*   **Alternatives**: InfluxDB (Not relational, harder to join with metadata), SQLite (Concurrency issues with multiple writers).

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** None detected.
