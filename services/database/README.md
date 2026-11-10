# silvasonic-database

> **Status:** Implemented (SQLite since ADR-0037) · **Tier:** 1 (Infrastructure) · **Engine:** SQLite (WAL mode) · **Instances:** Single file · **Port:** none

**AS-IS:** The station database is one SQLite file, `silvasonic.db`, in the `database/` workspace directory. It has no container and no server process. Every service with database access opens the file directly through `silvasonic.core.database`. The decision and what it gives up are in [ADR-0037](../../docs/adr/0037-sqlite-station-database.md).

---

## 1. The Problem / The Gap

*   **State Persistence:** Service configuration, device inventory, desired state, recordings, detections and upload history must survive reboots, container restarts and power loss.
*   **Limited Hardware:** A database server costs a Raspberry Pi hundreds of megabytes of RAM and needs an upgrade on every station in the field.

## 2. User Benefit

*   **Data Integrity:** Transactions (ACID) keep metadata consistent with the files on disk. With WAL and `synchronous = NORMAL`, a power loss can drop the last commits but never corrupts the file.
*   **Nothing to run:** No database container to start, wait for or upgrade. A backup is a file.

---

## 3. Core Responsibilities

### Inputs

*   **SQL from the services with DB access:** Controller, Processor, BirdNET, the development UIs and, as planned, the API service, BatDetect and Weather. **Not** the Recorder (ADR-0013).

### Processing

*   **Relational Storage:** Settings, Microphones, Microphone Profiles, Modules, Species, Users.
*   **Time-Ordered Storage:** Recordings, Detections, Weather Observations and Uploads, indexed by time.

### Outputs

*   **Result Sets:** Data for all consuming services and the Controller reconciliation loop.

---

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                                                        |
| ---------------- | --------------------------------------------------------------------------------------------------- |
| **Immutable**    | No (stateful by definition)                                                                         |
| **Location**     | `${SILVASONIC_WORKSPACE_PATH}/database/`, mounted read-write at `/data/database` (`:z`)            |
| **Concurrency**  | One writer at a time; readers never block. Every transaction is `BEGIN IMMEDIATE` and must be short |
| **Filesystem**   | Local disk only. Never NFS, SMB or FUSE: SQLite's locks need one kernel and a local file system      |
| **Privileges**   | Rootless; the directory, not only the file, must be writable (WAL and lock index live beside it)   |
| **Resources**    | A few MB of page cache per connection, inside each client                                           |

## 5. Configuration & Environment

| Variable / Mount          | Description                                  | Default / Example              |
| ------------------------- | -------------------------------------------- | ------------------------------ |
| `SILVASONIC_DB_PATH`      | The database file inside a container         | `/data/database/silvasonic.db` |
| `database/` (bind mount)  | Directory with the file and its `-wal`/`-shm` | `/data/database`               |

Every connection gets the same pragmas from `silvasonic.core.database.session`: `journal_mode = WAL`, `synchronous = NORMAL`, `foreign_keys = ON` and a busy timeout. No service sets its own.

---

## 6. Technology Stack

*   **Engine:** SQLite (the version the `python:3.13-slim-bookworm` base image ships, 3.40)
*   **Client Libraries:** `sqlalchemy` (2.0+ async), `aiosqlite`
*   **Inspection:** `sqlite3` on the host, the DB-Viewer in development

---

## 7. Out of Scope

*   **Does NOT** store large binary blobs — WAV/FLAC files reside on the filesystem, only paths are stored here.
*   **Does NOT** listen on a port — nothing outside the station reaches it; the API service will be the network interface (ADR-0032, planned).
*   **Does NOT** contain application logic — it is a passive data store.
*   **Does NOT** replicate to a fleet server — a station reports in API representations instead (ADR-0037).

---

## 8. Implementation Details (Domain Specific)

### Schema Management (Dev-Phase)

| Rule      | Detail                                                                                                                   |
| :-------- | :----------------------------------------------------------------------------------------------------------------------- |
| **Edit**  | Modify [`schema.sql`](../../packages/core/src/silvasonic/core/database/schema.sql) directly.                              |
| **Apply** | The first connection to a new file applies it and sets `PRAGMA user_version`. To start over, stop the stack and delete `database/`. |
| **Sync**  | Every change to the DDL **must** be mirrored in the SQLAlchemy models (`packages/core/…/models/`) and vice-versa.         |
| **Version** | A file with another `user_version` stops every service: the schema needs a migration, and the migration tool is decided before v1.0.0 (ADR-0033). |

Deleting `database/` keeps the recordings on disk (the Indexer finds them again) but loses detections and upload history. A database from before ADR-0033 and ADR-0037 (TimescaleDB, old table names) cannot be converted: start with an empty `database/`.

### Inspecting and Backing Up

```bash
# Read-only look at a running station
sqlite3 "file:$SILVASONIC_WORKSPACE_PATH/database/silvasonic.db?mode=ro" ".tables"

# Consistent copy while every service keeps running
sqlite3 "$SILVASONIC_WORKSPACE_PATH/database/silvasonic.db" "VACUUM INTO '/tmp/silvasonic-backup.db'"
```

Never copy the file with `cp` while services run: the latest commits may still sit in `silvasonic.db-wal`.

### Type Conventions

| Category        | Type in `schema.sql`                       | In Python                                |
| :-------------- | :----------------------------------------- | :--------------------------------------- |
| Identifiers     | `TEXT`, a UUIDv7 as 32 hex digits for rows created at runtime; readable slugs for authored entities | `uuid.UUID` via SQLAlchemy `Uuid` |
| Timestamps      | `INTEGER`, microseconds since the epoch (UTC) | aware `datetime` via `UTCDateTime`     |
| Booleans        | `INTEGER` 0/1 with a `CHECK`               | `bool`                                   |
| Strings         | `TEXT`                                     | `str`                                    |
| Structured data | `TEXT` with `CHECK (json_valid(…))`        | `dict` via SQLAlchemy `JSON`             |

Every table is `STRICT`, so SQLite rejects a value of the wrong type. The ORM generates UUIDv7 ids (`silvasonic.core.ids.uuid7`); the column default builds an equivalent one for raw SQL that leaves `id` out. Raw SQL (`text()`) bypasses the Python types: `silvasonic.core.database` registers adapters so a bound `uuid.UUID` or `datetime` is stored as the ORM stores it, but values read back come as stored — UUIDs as hex text, times as epoch microseconds, JSON as text, booleans as 0/1.

### Writing Without Blocking Others

*   Never hold a transaction open across inference, file I/O or a network call. End a read with `rollback()` before such work; write in a short transaction afterwards.
*   A transaction that holds the lock longer than one second is logged as `database.slow_transaction`.
*   Analysis workers claim a recording with one `UPDATE … RETURNING` and a lease, commit, and analyse without a transaction (ADR-0018, ADR-0037).

---

## 9. References

- [ADR-0037: SQLite as the Station Database](../../docs/adr/0037-sqlite-station-database.md) — the decision and its trade-offs
- [Database Schema (DDL)](../../packages/core/src/silvasonic/core/database/schema.sql) — SQL source of truth
- [SQLAlchemy Models](../../packages/core/src/silvasonic/core/database/models/) — ORM mirror
- [Filesystem Governance](../../docs/arch/filesystem_governance.md) — the `database/` workspace directory
- [Glossary](../../docs/glossary.md) — canonical definitions of all DB entities
- [VISION.md](../../VISION.md) — services architecture
