# ADR-0018: Worker Pull Orchestration — Self-Service Analysis via DB Polling

> **Status:** Accepted • **Date:** 2026-02-18

> **NOTE:** References to `birdnet`, `batdetect`, or `processor` refer to future services (planned for v0.3.0+). Currently, only `recorder` and `controller` exist.

## 1. Context & Problem

Analysis workers (BirdNET, BatDetect) need to process recordings produced by the Recorder and indexed by the Processor. The question is: **who decides what a worker should process next?**

Two fundamental patterns exist:

1.  **Push (Processor assigns work):** The Processor scans for unprocessed recordings and dispatches jobs to workers.
2.  **Pull (Workers self-serve):** Each worker independently queries the database for unprocessed recordings and claims work atomically.

The choice affects resilience, complexity, and coupling between services.

## 2. Decision

**We chose:** Worker Pull — each analysis worker independently polls the `recordings` table.

**Reasoning:**

### The Pull Pattern

Workers query the database directly for unanalyzed recordings:

```sql
SELECT id, file_processed
FROM recordings
WHERE analysis_state->>'birdnet' IS NULL
ORDER BY time ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;
```

*   `FOR UPDATE` locks the row to prevent concurrent workers from claiming the same recording.
*   `SKIP LOCKED` ensures other workers skip already-claimed rows instead of blocking — no contention.
*   On completion, the worker updates `analysis_state->>'birdnet' = 'true'`.

### Processor Role: Ingestion + Janitor Only

The Processor's responsibilities are strictly:

1.  **Ingestion:** Watch Recorder workspace via filesystem polling, create `recordings` entries in the database.
2.  **Janitor:** Enforce the Data Retention Policy (ADR-0011 §6) by deleting old files based on disk thresholds.

The Processor does **not** track worker availability, assign jobs, or maintain a work queue.

## 3. Options Considered

*   **Push model (Processor distributes):** Rejected. Makes the Processor a single point of failure — if it crashes, no new work is assigned even though workers and the database are healthy. Adds state management complexity (tracking worker availability, retrying failed dispatches).
*   **Redis-based job queue:** Rejected. Adds a runtime dependency on Redis for the critical analysis path. Workers already have DB access (ADR-0013) — adding Redis as an intermediary is unnecessary indirection.
*   **File-based signaling (`.ready` marker files):** Rejected. Fragile, no atomicity guarantees, requires filesystem coordination between services.

## 4. Consequences

*   **Positive:**
    *   **No SPOF:** Workers operate autonomously. Processor failure does not block analysis of already-indexed recordings.
    *   **No Redis dependency:** Worker orchestration works with the database alone — available from v0.3.0 without waiting for Redis.
    *   **Atomic claims:** `FOR UPDATE SKIP LOCKED` prevents double-processing without application-level locking.
    *   **Scalable:** Adding a second BirdNET instance (future) requires zero coordination changes — both poll the same table.
    *   **Simple:** No job queue, no dispatcher, no worker registry.
*   **Negative:**
    *   Workers must poll periodically (e.g., every 30s), adding minor DB query load.
    *   No instant notification when new recordings are available — there is a polling delay. If needed in the future, a lightweight Redis notification (`PUBLISH`) can be added as an optimization without changing the core pull architecture.
