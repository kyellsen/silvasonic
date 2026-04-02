# ADR-0025: Recordings Table — Standard PostgreSQL Table (No Hypertable)

> **Status:** Accepted • **Date:** 2026-03-26

## 1. Context & Problem

The `recordings` table serves as the central inventory for all audio files captured by Recorder instances. Two other tables reference it via Foreign Keys:

*   `detections.recording_id → recordings.id`
*   `uploads.recording_id → recordings.id`

TimescaleDB Hypertables do **not** support incoming Foreign Key constraints. Converting `recordings` to a Hypertable would require dropping these FKs or implementing application-level referential integrity.

The question: does `recordings` benefit enough from Hypertable features (automatic partitioning, native compression, continuous aggregates) to justify removing FK constraints?

## 2. Decision

**We chose:** Keep `recordings` as a standard PostgreSQL table. Optimize query performance with targeted indices, specifically a partial index for the Worker Pull pattern (ADR-0018).

**Reasoning:**

### Low Data Volume

A single microphone at 30-second segments produces ~2,880 rows/day. With 2 microphones: ~6,000 rows/day, ~2 million rows/year. At ~300 bytes per row, the table grows by ~600 MB/year. PostgreSQL handles this trivially without partitioning.

### Catalog, Not Time-Series

Unlike `weather` and `detections` (which are true time-series with high insert rates and range-scan queries), `recordings` is a **status-tracking catalog**. Its primary query patterns are:

*   Worker Pull: `SELECT ... WHERE analysis_state->>'worker' IS NULL AND local_deleted = false ... FOR UPDATE SKIP LOCKED` (ADR-0018)
*   Janitor: `SELECT ... WHERE uploaded = true AND local_deleted = false ORDER BY time ASC`
*   Dashboard: count/status aggregations

These are classic OLTP queries that benefit from B-Tree indices, not chunk-based partitioning.

### FK Constraints Are Critical

The `detections` table (a Hypertable itself) references `recordings.id`. Dropping this FK would mean a bug in BirdNET or BatDetect could insert detections pointing to non-existent recordings — violating data integrity silently. Enforcing referential integrity in application code across multiple independent services (BirdNET, BatDetect) contradicts the KISS principle and the Zero-Trust philosophy (ADR-0009).

### Worker Pull Performance

The `FOR UPDATE SKIP LOCKED` pattern (ADR-0018) works optimally on standard tables. On Hypertables, the query planner must scan across chunks, adding overhead for no benefit at this data volume. A partial index provides microsecond-level performance:

```sql
CREATE INDEX ix_recordings_analysis_pending
ON recordings (time ASC)
WHERE local_deleted = false;
```

## 3. Options Considered

*   **Hypertable + Drop FKs:** Rejected. Sacrifices database-enforced referential integrity for partitioning features that are unnecessary at this data volume. Pushes integrity checks into application code — fragile and hard to audit.
*   **Hypertable + FK Workaround (Triggers):** Rejected. TimescaleDB fundamentally does not support incoming FKs. Trigger-based workarounds are fragile, slow, and constitute overengineering. Additionally, `detections` is already a Hypertable — Hypertable-to-Hypertable FK constraints are not supported at all.
*   **Standard Table + Indices (chosen):** FK constraints remain. A partial index optimizes the Worker Pull query. No partitioning overhead, no workarounds, no complexity.

## 4. Consequences

*   **Positive:**
    *   Referential integrity between `recordings`, `detections`, and `uploads` is enforced by the database — zero application-level validation needed.
    *   `FOR UPDATE SKIP LOCKED` works without chunk-scan overhead.
    *   No TimescaleDB-specific complexity or workarounds.
    *   Schema remains simple and auditable.
*   **Negative:**
    *   No automatic chunk-based compression or retention. If the table grows beyond expectations (unlikely given the Janitor's `local_deleted` lifecycle), manual `VACUUM` tuning or table partitioning can be added later.
    *   No continuous aggregates on `recordings`. Dashboard statistics must use standard SQL aggregation (sufficient for ~2M rows/year).
