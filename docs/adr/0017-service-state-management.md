# ADR-0017: Service State Management — Desired vs. Actual State

> **Status:** Accepted • **Date:** 2026-02-18

## 1. Context & Problem

The `system_services` table tracks services, but its `status` column has ambiguous semantics. "Status" could mean either the **desired** operational mode (what an admin wants) or the **actual** runtime state (what the service is currently doing). Without a clear split, the system conflates configuration with observation, making it impossible to detect drift (e.g., a service *should* be active but has crashed).

Additionally, the Web-Interface needs real-time visibility into service health. Polling the database for runtime state introduces latency, couples the UI to the DB, and forces every service to write frequent status updates into a transactional store — a poor fit for ephemeral heartbeat data.

## 2. Decision

**We chose:** A strict separation of Desired State (database) and Actual State (Redis Pub/Sub).

**Reasoning:**

### Desired State → Database (`system_services`)

The `system_services` table holds **configuration and intent**:

*   `enabled` (BOOLEAN): Should the service run at all?
*   `status` (TEXT): Desired operational mode — values like `active`, `standby`, `disabled`.

This is written by admins or the Web-Interface and read by the Controller to determine what *should* be running.

### Actual State → Redis Pub/Sub (v0.6.0)

Runtime health and activity (healthy, degraded, crashed, recording, idle) is **ephemeral** and published to Redis:

*   Each service publishes its own heartbeat to `silvasonic.status` (Redis Pub/Sub).
*   The Controller publishes Tier 2 container status based on its `podman-py` reconciliation loop.
*   The Web-Interface subscribes to `silvasonic.status` for real-time display — **no DB polling required**.

### No Separate Monitor Service

Monitoring is distributed, not centralized:

*   **Controller** → Watches Tier 2 containers (podman-py, reconciliation loop, ADR-0013).
*   **Each Service** → Publishes its own heartbeat to Redis.
*   **Web-Interface** → Subscribes to Redis Pub/Sub, displays live dashboard.
*   **Podman** → Restart policy (`on-failure`) as the last safety net.

A dedicated Monitor service was rejected as over-engineering for a single-node edge device. External alerting (e-mail on failure) can be a future Web-Interface feature.

## 3. Options Considered

*   **Database-only (status + last_seen column):** Rejected. Requires DB polling for UI, adds write load for heartbeats, and mixes ephemeral runtime data with persistent configuration.
*   **Redis-only (remove system_services):** Rejected. Desired state must survive Redis restarts. DB is the right home for configuration.
*   **Separate Monitor service:** Rejected. Adds complexity without proportional value on a single-node device. The Controller already monitors Tier 2 via podman-py, and the Web-Interface can subscribe to Redis directly.

## 4. Consequences

*   **Positive:**
    *   Clear semantic split: DB = "what should be", Redis = "what is".
    *   Web-Interface gets real-time status from day one (v0.6.0) via Pub/Sub — no DB polling.
    *   No separate Monitor service — fewer containers, less complexity.
    *   `system_services` table schema unchanged — only its semantics are clarified.
*   **Negative:**
    *   Redis becomes a dependency for live status visibility (but not for recording or data integrity).
    *   If Redis is down, the Web-Interface loses real-time status. Desired state from DB remains accessible.
    *   No persistent history of runtime state (heartbeats are ephemeral). If needed later, an audit trail can be added to the DB.
