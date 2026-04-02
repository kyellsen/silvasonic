# silvasonic-database

> **Status:** Implemented (since v0.1.0) · **Tier:** 1 (Infrastructure) · **Engine:** TimescaleDB / PostgreSQL · **Instances:** Single · **Port:** 5432

**AS-IS:** Central persistent store for the Silvasonic system — relational metadata and time-series data powered by TimescaleDB on PostgreSQL.

---

## 1. The Problem / The Gap

*   **Time-Series Data:** Bioacoustic data generates millions of rows (recordings, detections, weather observations) ordered by time. Standard SQL databases degrade in performance at this volume without specialized partitioning.
*   **State Persistence:** Service configuration, device inventory, and desired state must persist across reboots and container restarts.

## 2. User Benefit

*   **Fast Queries:** TimescaleDB hypertables allow querying "last 24 hours of detections" in milliseconds, even with millions of rows.
*   **Data Integrity:** Transactional guarantees (ACID) ensure metadata always matches files on disk.

---

## 3. Core Responsibilities

### Inputs

*   **SQL Queries:** INSERT / SELECT / UPDATE from all services with DB access (Controller, Processor, BirdNET, BatDetect, Weather, Web-Interface). **Not** from the Recorder (ADR-0013).

### Processing

*   **Relational Storage:** System Config, Devices, Microphone Profiles, Storage Remotes, System Services, Taxonomy.
*   **Time-Series Storage:** Detections and Weather Observations via TimescaleDB hypertables (partitioned by `time`).
*   **Compression:** (Future) Auto-compressing old chunks via TimescaleDB continuous aggregates and compression policies.

### Outputs

*   **Result Sets:** Data for all consuming services, the Web-Interface API, and the Controller reconciliation loop.

---

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                                |
| ---------------- | --------------------------------------------------------------------------- |
| **Immutable**    | No (Stateful by definition)                                                 |
| **DB Access**    | N/A (This **is** the database)                                              |
| **Concurrency**  | High (Optimized via PostgreSQL `asyncpg` bindings)                            |
| **State**        | Stateful (Named Volume `db-data`)                                           |
| **Privileges**   | Rootless (Podman rootless mode, no `USER` directive)                        |
| **Resources**    | Medium (Steady memory footprint, I/O bound)                                |
| **QoS Priority** | `oom_score_adj=0` (Default Tier 1)                                          |

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

---

## 6. Technology Stack

*   **Engine:** PostgreSQL 17
*   **Extension:** TimescaleDB 2.19.3
*   **Base Image:** `timescale/timescaledb:2.19.3-pg17`
*   **Client Libraries:** `sqlalchemy` (2.0+ async), `asyncpg` (in consuming services)

---

## 7. Out of Scope

*   **Does NOT** store large binary blobs — WAV/FLAC files reside on the filesystem, only paths are stored here.
*   **Does NOT** expose ports to the internet — internal `silvasonic-net` only (Gateway handles external access).
*   **Does NOT** contain application logic — it is a passive data store.
*   **Does NOT** authenticate end-users — Gateway and Web-Interface handle authentication.
*   **Does NOT** compress audio files (Processor Cloud-Sync-Worker's job).

---

## 8. Implementation Details (Domain Specific)
### Schema Management (Dev-Phase)

| Rule      | Detail                                                                                                                |
| :-------- | :-------------------------------------------------------------------------------------------------------------------- |
| **Edit**  | Always modify [`01-init-schema.sql`](init/01-init-schema.sql) directly.                                               |
| **Apply** | Tear down the database container and recreate — no incremental migrations during dev.                                 |
| **Sync**  | Every change to the SQL DDL **must** be mirrored in the SQLAlchemy models (`packages/core/…/models/`) and vice-versa. |

---

### Type Conventions

| Category        | Type                                         |
| :-------------- | :------------------------------------------- |
| Identifiers     | `BIGINT GENERATED BY DEFAULT AS IDENTITY`    |
| Timestamps      | `TIMESTAMPTZ` (= `TIMESTAMP WITH TIME ZONE`) |
| Strings         | `TEXT` (never `VARCHAR`)                     |
| Structured data | `JSONB`                                      |

---

### Hypertable Constraints (TimescaleDB)

- `detections` and `weather` are **hypertables** partitioned by `time`.
- TimescaleDB does **not** support Foreign Keys **referencing** a hypertable.
  → `recordings` must remain a **standard table** so that `detections` and `uploads` can reference it via FK.
- The partition key (`time`) **must** be part of the composite primary key on every hypertable.

---

## 9. References

- [Database Schema (DDL)](init/01-init-schema.sql) — SQL source of truth
- [SQLAlchemy Models](../../packages/core/src/silvasonic/core/database/models/) — ORM mirror
- [ADR-0006: Bind Mounts over Volumes](../../docs/adr/0006-bind-mounts-over-volumes.md) — Named Volume exception for database
- [Port Allocation](../../docs/arch/port_allocation.md) — Database on port 5432
- [Glossary](../../docs/glossary.md) — canonical definitions of all DB entities
- [VISION.md](../../VISION.md) — services architecture
