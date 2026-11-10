# ADR-0037: SQLite as the Station Database

> **Status:** Accepted • **Date:** 2026-11-10 • **Supersedes:** [ADR-0026](0026-timescaledb-edge-analytics.md)

## 1. Context & Problem

ADR-0026 chose TimescaleDB for the station. It rejected SQLite for two reasons: analysis workers claim recordings concurrently with `FOR UPDATE SKIP LOCKED`, and the local dashboard must answer ten-year statistics without scanning hundreds of millions of rows. Several things look different now:

*   **The station uses no TimescaleDB feature.** The init schema creates two hypertables (`detections`, `weather`). Nothing uses compression, retention policies, continuous aggregates or `time_bucket`. Of PostgreSQL itself the code uses five things, and SQLite has an equivalent for each:

    | PostgreSQL | Used in | SQLite equivalent |
    | --- | --- | --- |
    | `FOR UPDATE SKIP LOCKED` | BirdNET claim | a short claim transaction (§2) |
    | `JSONB`, `has_key` | BirdNET, six models | `JSON`, `json_extract` / `->>` |
    | `= ANY(array)` | Indexer, Janitor | `IN (…)` |
    | `ON CONFLICT DO NOTHING` | Seeder | identical syntax |
    | `TIMESTAMPTZ` | four models | a shared column type (§2) |

*   **The fleet server takes the long view.** A fleet server aggregates many stations ([ADR-0032](0032-api-first-station-contract.md)), and that is where hypertables, compression and continuous aggregates pay off. A station needs its recent data in full and its own long-term statistics. It does not need a time-series engine for that.
*   **The engine costs the station memory and upkeep.** The database takes about 300–450 MB of RAM (ADR-0026). The minimum platform is a Raspberry Pi 5 with 4 GB ([hardware](../hardware.md)), which also runs BirdNET and later BatDetect. On top of that come a 765 MB image and a healthcheck that every database client waits for at boot. Each PostgreSQL or TimescaleDB major upgrade has to be carried out on every station in the field.
*   **Concurrency is low.** These services write: the Controller, the Processor (Indexer, Janitor, Cloud-Sync-Worker), BirdNET and, as planned, the API service, Weather and BatDetect. Together they produce a few writes per second. Each analyzer runs one instance.
*   **The schema is rewritten once anyway.** [ADR-0033](0033-unified-naming-and-global-identifiers.md) changes every table in place before the first release. After that, every change needs a migration on every station, a switch of engine included.

## 2. Decision

**We chose:** SQLite in WAL mode as the station database. It is one file on the NVMe, opened directly by each service that has database access today. Redis keeps its role. The fleet server chooses its own engine, and TimescaleDB fits there.

**Reasoning:** each property we give up has a concrete replacement.

*   **One writer at a time.** SQLite serialises write transactions. Readers neither block nor are blocked. A few writes per second leave ample room, as long as no write transaction is long:
    *   Every write transaction starts with `BEGIN IMMEDIATE` and waits up to `busy_timeout` rather than failing at once. A `database is locked` error after the timeout is a transient error under [ADR-0030](0030-database-resilience.md).
    *   No lock is held while analysis runs. Today BirdNET holds its row lock for the whole inference. Under SQLite a worker instead:
        1.  claims a recording in one short transaction (`UPDATE … SET analysis_state = running, claimed_at = now WHERE id = (SELECT … LIMIT 1) RETURNING …`) and commits;
        2.  analyses with no transaction open;
        3.  writes its detections and the final state in a second short transaction.

        Another worker may take over a claim older than its lease, so a crashed worker loses nothing. The Worker Pull pattern of [ADR-0018](0018-worker-pull-orchestration.md) stays; only its SQL changes.
    *   A write transaction never contains inference, file I/O or a network call.
*   **A local file, shared by bind mount.** SQLite's locks and its WAL index need a local file system and one kernel for all clients. The station meets both conditions: every database client mounts the database directory read-write (`:z`). The file never lies on NFS, SMB or FUSE. The Recorder still has no database access, and the Consumer Principle for audio ([ADR-0009](0009-zero-trust-data-sharing.md)) is unaffected.
*   **Integrity is enforced by us, in one place.** Tables are `STRICT`. `silvasonic.core.database` is the only place that opens connections. It sets these on every connection:
    *   `journal_mode = WAL`
    *   `synchronous = NORMAL`
    *   `foreign_keys = ON`
    *   `busy_timeout`

    A shared column type stores times as integer microseconds since the Unix epoch (UTC) and returns timezone-aware `datetime` values. JSON columns are `JSON`, with a `JSONB` variant where a model also runs on PostgreSQL.
*   **The application generates identifiers.** ADR-0033 lets PostgreSQL generate UUIDv7 values. On SQLite the core package generates them and stores them as 16-byte `BLOB`s. Detections no longer need the composite key a hypertable required: they are keyed by `id`, with an index on `started_at`.
*   **Long-term statistics come from rollups.** These replace continuous aggregates. Whoever writes a detection also increments a counter per microphone, species and hour, in the same transaction. Ten years of rollups come to a few million rows, and a ten-year chart reads them through an index. The same table is the result a station on a metered connection reports ([ADR-0038](0038-connection-classes-and-upload-path.md)).
*   **Retention is a batched delete.** The Janitor deletes old detections in batches and keeps the rollups. Without chunk compression a detection row costs its full size, roughly 300 bytes with its indexes (estimate). ADR-0026's projection of 350 million rows would then fill about 100 GB. The station therefore keeps detections in full for a configurable horizon and statistics indefinitely. The full history lives on the fleet server or in exports (v1.4.0).
*   **A backup is a file.** `VACUUM INTO` writes a consistent copy while every service keeps running.
*   **Migrations rebuild tables.** SQLite's `ALTER TABLE` cannot change a column's type or constraints, so a migration that does copies the table. ADR-0033 leaves the migration tool to a later ADR, and that tool must support this (Alembic's batch mode does).

## 3. Options Considered

*   **Keep TimescaleDB (ADR-0026):** Rejected. Its reasons hold for a fleet server. A station uses none of its features yet pays for them in memory and in an engine upgrade per station.
*   **Plain PostgreSQL:** Rejected. It drops only the extension and keeps the server process, the memory floor, the container and the upgrades.
*   **One service owns the SQLite file and serves it to the others over the network:** Rejected. It brings back a server process and a protocol to replace the one this decision removes. The API service is already the station's one network interface ([ADR-0032](0032-api-first-station-contract.md)).
*   **DuckDB:** Rejected. It is built for analytical scans, and only one process can open a database file for writing. The services are separate processes in separate containers.
*   **An embedded key-value store (LMDB, RocksDB):** Rejected. It offers no SQL and no SQLAlchemy, so every query would have to be written as code.
*   **Replicating the database to the fleet (libSQL, LiteFS, PostgreSQL logical replication):** Rejected. A station reports to the fleet in API representations (ADR-0032), tier by tier, within what its connection allows ([ADR-0038](0038-connection-classes-and-upload-path.md)). Page or row replication would send what a metered link must not carry, and it would tie the fleet's schema to the station's.

## 4. Consequences

*   **Positive:**
    *   Roughly 300–450 MB of RAM go back to analysis. The SQLite page cache lives in each client process and totals a few tens of MB (estimate).
    *   The station runs one container and one image fewer. Services start without waiting for a database healthcheck.
    *   No database server needs upgrading on any station. The SQLite file format has been stable and backward compatible since 2004.
    *   An integration test opens a temporary file instead of starting a TimescaleDB container.
    *   There is no database port to configure or protect.
    *   A service rewritten in another language opens the same file with its own SQLite driver.
*   **Negative:**
    *   The claim in BirdNET (and later BatDetect) is rewritten with a lease.
    *   Nobody can reach the database from another machine any more (`psql`, DBeaver, Grafana). Inspection runs on the station (`sqlite3`, the DB-Viewer) or through the API.
    *   A long write transaction now blocks every other writer, so the engine no longer guards against it. `silvasonic.core.database` logs any write transaction above a threshold.
    *   A long read transaction keeps the WAL from being checkpointed, and the WAL grows until it ends. Dashboard queries stay short, and the Janitor checkpoints regularly (`wal_checkpoint(TRUNCATE)`).
    *   A model shared with the fleet server must work on both dialects, and its tests run against both.
*   **Timing:** the switch lands with ADR-0033's schema rewrite, before v1.0.0. No station then ever holds a PostgreSQL database that would need migrating to SQLite.
*   **On acceptance these documents change:**
    *   ADR-0026 becomes Superseded.
    *   ADR-0018 gets the new claim.
    *   ADR-0025: the hypertable distinction becomes moot.
    *   ADR-0033: identifier generation and the detection key change.
    *   ADR-0030: lock timeouts count as transient errors.
    *   ADR-0006 and AGENTS.md §4: named volumes for the database.
    *   AGENTS.md §5: `asyncpg` becomes `aiosqlite`, and `testcontainers` is no longer needed for the database.
    *   VISION.md: the service table.
    *   Also changed: `docs/services/database.md`, `docs/arch/filesystem_governance.md`, `compose.yml` and `.env.example` (`SILVASONIC_DB_*`, `POSTGRES_*`).
