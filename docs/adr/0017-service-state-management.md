# ADR-0017: Service State Management — Desired vs. Actual State

> **Status:** Accepted • **Date:** 2026-02-18 • **Updated:** 2026-02-21

## 1. Context & Problem

The `system_services` table tracks services, but its `status` column has ambiguous semantics. "Status" could mean either the **desired** operational mode (what an admin wants) or the **actual** runtime state (what the service is currently doing). Without a clear split, the system conflates configuration with observation, making it impossible to detect drift (e.g., a service *should* be active but has crashed).

Additionally, the Web-Interface needs real-time visibility into service health. Polling the database for runtime state introduces latency, couples the UI to the DB, and forces every service to write frequent status updates into a transactional store — a poor fit for ephemeral heartbeat data.

## 2. Decision

**We chose:** A strict separation of Desired State (database) and Actual State (Redis), with a **unified heartbeat pattern** for all services.

**Reasoning:**

### Desired State → Database

The `system_services` table holds **configuration and intent**:

*   `enabled` (BOOLEAN): Should the service run at all?
*   `status` (TEXT): Desired operational mode — values like `active`, `standby`, `disabled`.

This is written by admins or the Web-Interface and read by the Controller to determine what *should* be running.

**Scope:** The `system_services` table is used for:
*   **Tier 1 services** (Processor, Web-Interface, Icecast, etc.)
*   **Tier 2 singletons** (BirdNET, BatDetect, Weather)

For multi-instance Tier 2 services, the Controller derives desired state from domain tables:
*   **Recorder:** `devices` + `microphone_profiles` (one Recorder per enrolled device)
*   **Uploader:** `storage_remotes` (one Uploader per remote target)

### Actual State → Redis (v0.2.0)

Runtime health and activity is **ephemeral** and stored in Redis via two complementary mechanisms:

1.  **`SET silvasonic:status:<instance_id>`** with 30s TTL — current status snapshot, readable anytime.
2.  **`PUBLISH silvasonic:status`** — live updates for subscribers (Web-Interface).

This is the **Read + Subscribe Pattern:** The Web-Interface reads all `silvasonic:status:*` keys on page load for the initial state, then subscribes to `silvasonic:status` for live updates. No missed heartbeats, no polling.

### Unified Heartbeat — All Services, Including Recorder

**Every** Python service publishes its own heartbeat to Redis via the `SilvaService` base class (see [ADR-0019](0019-unified-service-infrastructure.md)). This includes the Recorder.

*   The heartbeat runs in an isolated `asyncio.Task`, completely decoupled from the service's core logic.
*   `PUBLISH` and `SET` operations are fire-and-forget with a 50ms timeout.
*   Any Redis failure is silently caught — the service continues without interruption.
*   The recording loop has **zero coupling** to the heartbeat task.

> [!IMPORTANT]
> Redis is as stable as TimescaleDB on this hardware (same host, NVMe, no network). The fire-and-forget pattern is not motivated by distrust of Redis — it reflects the principle that a service's core function should never be blocked by a non-essential operation.

### Control via DB + Reconcile-Nudge (State Reconciliation Pattern)

Control flows through the **Database** (desired state), not through HTTP API or Redis commands:

1.  The Web-Interface writes the desired state to the database (e.g., `enabled=false` in `system_services`).
2.  A simple `PUBLISH silvasonic:nudge "reconcile"` wakes the Controller immediately (instead of waiting for the 30s timer).
3.  The Controller reads the DB, compares desired vs. actual state, and acts via `podman-py`.

This follows the **Kubernetes Operator Pattern** (State Reconciliation) adapted for a single-node system:

*   **DB is the Single Source of Truth** — commands are never lost. If the Controller restarts, it reads the DB and applies the desired state automatically.
*   **The Controller has no HTTP API** (beyond the `/healthy` health endpoint). It is a pure **Listener + Actor**: subscribe to nudge, read DB, act via Podman.
*   **Immutable services** (Recorder, Workers, Processor) do not process runtime commands — they are stopped and restarted with new configuration by the Controller.

For details see [controller.md](../services/controller.md) and [Messaging Patterns](../arch/messaging_patterns.md).

### Monitoring: Distributed, Not Centralized

*   **Each Service** → Publishes its own heartbeat to Redis (via `SilvaService`).
*   **Controller** → Additionally publishes Tier 2 container status based on its `podman-py` reconciliation loop (for containers that may not have Redis connectivity yet during startup).
*   **Web-Interface** → Subscribes to Redis, displays live dashboard.
*   **Podman** → Restart policy (`on-failure`) as the last safety net.

A dedicated Monitor service was rejected as over-engineering for a single-node edge device. External alerting (e-mail on failure) can be a future Web-Interface feature.

## 3. Options Considered

*   **Database-only (status + last_seen column):** Rejected. Requires DB polling for UI, adds write load for heartbeats, and mixes ephemeral runtime data with persistent configuration.
*   **Redis-only (remove system_services):** Rejected. Desired state must survive Redis restarts. DB is the right home for configuration.
*   **Separate Monitor service:** Rejected. Adds complexity without proportional value on a single-node device.
*   **Redis Streams for lifecycle/control/audit:** Rejected. Lifecycle events are derivable from heartbeats, control flows through DB + Nudge, and business events (recording finished, upload completed) are already tracked in the DB. Four separate channels add complexity without proportional value — one Pub/Sub channel + key-value pattern + nudge covers all needs.
*   **Controller HTTP API for control commands:** Rejected. Imperative commands ("stop now!") can be lost if the Controller restarts. The State Reconciliation pattern (DB write + nudge) is more robust: desired state is always persisted, and reconciliation is idempotent.
*   **Recorder without Redis:** Rejected. Creates a non-uniform pattern where the Controller must proxy Recorder status. With fire-and-forget heartbeats, the Recorder's core function is completely unaffected, and the Web-Interface gets direct, real-time status from all services.

## 4. Consequences

*   **Positive:**
    *   Clear semantic split: DB = "what should be", Redis = "what is".
    *   **Unified pattern:** Every service uses the same `SilvaService` heartbeat — no special cases.
    *   Web-Interface gets real-time status from day one (v0.8.0) via Read + Subscribe — no DB polling, no missed heartbeats.
    *   No separate Monitor service — fewer containers, less complexity.
    *   `system_services` table schema unchanged — only its semantics are clarified.
    *   Minimal Redis footprint: one Pub/Sub channel + N keys with TTL. No Streams, no Consumer Groups.
*   **Negative:**
    *   Redis becomes a dependency for live status visibility (but not for recording, analysis, or data integrity).
    *   If Redis is down, the Web-Interface loses real-time status. Desired state from DB remains accessible.
    *   No persistent history of runtime state (heartbeats are ephemeral). If needed later, an audit trail can be added to the DB.
    *   `redis-py` becomes a dependency for all services (including Recorder). The library is ~60 KB pure Python with zero C dependencies.
