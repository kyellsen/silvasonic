# Database Service

> **Status:** Implemented (v0.1.0) · **Tier:** 1 · **Instances:** Single · **Port:** 5432

Central persistent store for the Silvasonic system — relational metadata and time-series data powered by TimescaleDB on PostgreSQL.

---

## 1. The Problem / The Gap

*   **Time-Series Data:** Bioacoustic data generates millions of rows (recordings, detections, weather observations) ordered by time. Standard SQL databases degrade in performance at this volume without specialized partitioning.
*   **State Persistence:** Service configuration, device inventory, and desired state must persist across reboots and container restarts.

## 2. User Benefit

*   **Fast Queries:** TimescaleDB hypertables allow querying "last 24 hours of detections" in milliseconds, even with millions of rows.
*   **Data Integrity:** Transactional guarantees (ACID) ensure metadata always matches files on disk.

## 3. Core Responsibilities

### Inputs

*   **SQL Queries:** INSERT / SELECT / UPDATE from all services with DB access (Controller, Processor, BirdNET, BatDetect, Weather, Uploader, Web-Interface). **Not** from the Recorder (ADR-0013).

### Processing

*   **Relational Storage:** System Config, Devices, Microphone Profiles, Storage Remotes, System Services, Taxonomy.
*   **Time-Series Storage:** Detections and Weather Observations via TimescaleDB hypertables (partitioned by `time`).
*   **Compression:** (Future) Auto-compressing old chunks via TimescaleDB continuous aggregates and compression policies.

### Outputs

*   **Result Sets:** Data for all consuming services, the Web-Interface API, and the Controller reconciliation loop.

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                                |
| ---------------- | --------------------------------------------------------------------------- |
| **Immutable**    | No — stateful by definition                                                 |
| **DB Access**    | N/A — this **is** the database                                              |
| **Concurrency**  | High — optimized for many concurrent connections (via `asyncpg` in clients) |
| **State**        | Stateful — the single most critical volume (`db-data`)                      |
| **Privileges**   | Rootless (Podman rootless mode, no `USER` directive — ADR-0004)             |
| **Resources**    | Medium — steady memory footprint, I/O bound                                 |
| **QoS Priority** | `oom_score_adj=0` (default) — Tier 1 infrastructure                         |

> [!IMPORTANT]
> The database uses a **Named Volume** (`db-data`), which is the only exception to the Bind Mount policy (ADR-0006, AGENTS.md §4). This ensures PostgreSQL data integrity across container rebuilds.

## 5. Configuration & Environment

| Variable / Mount     | Description                 | Default / Example          |
| -------------------- | --------------------------- | -------------------------- |
| `POSTGRES_USER`      | Database superuser name     | `silvasonic`               |
| `POSTGRES_PASSWORD`  | Database superuser password | `silvasonic`               |
| `POSTGRES_DB`        | Default database name       | `silvasonic`               |
| `SILVASONIC_DB_PORT` | Host-exposed port           | `5432`                     |
| `db-data` (Volume)   | Named Volume for PGDATA     | `/var/lib/postgresql/data` |

> [!NOTE]
> `POSTGRES_*` variables are a third-party naming exception per AGENTS.md §7 — they follow the TimescaleDB/PostgreSQL image convention.

## 6. Technology Stack

*   **Engine:** PostgreSQL 17
*   **Extension:** TimescaleDB 2.19.3
*   **Base Image:** `timescale/timescaledb:2.19.3-pg17`
*   **Client Libraries:** `sqlalchemy` (2.0+ async), `asyncpg` (in consuming services)

## 7. Open Questions & Future Ideas

*   TimescaleDB continuous aggregates for pre-computed hourly/daily detection summaries
*   Compression policies for old hypertable chunks (detections, weather)
*   Backup strategy for NVMe-based deployments (pg_dump vs. WAL archiving)
*   Alternatives considered and rejected: InfluxDB (not relational, harder to join with metadata), SQLite (concurrency issues with multiple writers)

## 8. Out of Scope

*   **Does NOT** store large binary blobs — WAV/FLAC files reside on the filesystem, only paths are stored here.
*   **Does NOT** expose ports to the internet — internal `silvasonic-net` only (Gateway handles external access).
*   **Does NOT** contain application logic — it is a passive data store.
*   **Does NOT** authenticate end-users — Gateway and Web-Interface handle authentication.
*   **Does NOT** compress audio files (Uploader's job).

## 9. References

*   [Database README](../../services/database/README.md) — schema management, type conventions, hypertable constraints
*   [Database Schema (DDL)](../../services/database/init/01-init-schema.sql) — SQL source of truth
*   [ADR-0006](../adr/0006-bind-mounts-over-volumes.md) — Named Volume exception for database
*   [Port Allocation](../arch/port_allocation.md) — Database on port 5432
*   [Glossary](../glossary.md) — canonical definitions of all DB entities
*   [VISION.md](../../VISION.md) — services architecture
