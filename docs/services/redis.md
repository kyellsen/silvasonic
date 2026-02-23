# Redis

> **Status:** implemented · **Tier:** 1 · **Instances:** Single

**TO-BE:** In-memory data store serving as the real-time status bus for the Silvasonic ecosystem. Provides two mechanisms: key-value snapshots with TTL (current state) and Pub/Sub channels (live updates, nudge signals).

---

## 1. The Problem / The Gap

*   **No Real-Time Status:** Without Redis, the Web-Interface has no way to display live service health — it would need to poll each service individually.
*   **No Immediate Control:** The State Reconciliation Pattern requires a wake-up signal (`nudge`) so the Controller acts immediately instead of waiting for its 30s timer.

## 2. User Benefit

*   **Live Dashboard:** The Web-Interface shows real-time health and activity of all services via the Read+Subscribe Pattern.
*   **Instant Response:** When a user toggles a service in the Web-Interface, the Controller receives the nudge within milliseconds.

## 3. Core Responsibilities

### Inputs

*   Heartbeat payloads from all services via `SET silvasonic:status:<id> <json> EX 30`.
*   Nudge signal from Web-Interface via `PUBLISH silvasonic:nudge "reconcile"`.

### Processing

*   Key expiry (TTL) — keys auto-expire after 30s if a service stops publishing.
*   Pub/Sub message relay — zero processing, pure message passthrough.

### Outputs

*   Status snapshots readable via `KEYS silvasonic:status:*` + `GET`.
*   Live update stream subscribable via `SUBSCRIBE silvasonic:status`.

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                              |
| ---------------- | --------------------------------------------------------- |
| **Immutable**    | No (managed by Compose/Quadlet, standard Redis config)    |
| **DB Access**    | No — Redis is independent of PostgreSQL                   |
| **Concurrency**  | Single-threaded event loop (Redis default)                |
| **State**        | Ephemeral — all data is volatile, no persistence required |
| **Privileges**   | Rootless (ADR-0007)                                       |
| **Resources**    | Low — minimal memory footprint (< 10 MB)                  |
| **QoS Priority** | `oom_score_adj=0` (default) — Tier 1 infrastructure       |

> [!IMPORTANT]
> Redis is **best-effort infrastructure**. If Redis goes down, the critical path (recording, ingestion, analysis) continues uninterrupted via filesystem/DB polling. Only the Web-Interface loses real-time status updates. See [Messaging Patterns](../arch/messaging_patterns.md) §1.1.

## 5. Configuration & Environment

| Variable / Mount        | Description            | Default / Example  |
| ----------------------- | ---------------------- | ------------------ |
| `SILVASONIC_REDIS_PORT` | Host-exposed port      | `6379`             |
| Named Volume            | Redis data (ephemeral) | `silvasonic-redis` |

## 6. Technology Stack

*   **Image:** `redis:7-alpine` (official, minimal)
*   **Persistence:** None (`--save ""` or default, data is volatile)

## 7. Open Questions & Future Ideas

*   Redis Sentinel or replication: Not needed for single-device deployment.
*   Persistence: Currently disabled. Could enable AOF if nudge reliability becomes critical.

## 8. Out of Scope

*   **Does NOT** store persistent state (Database's job).
*   **Does NOT** queue work for workers (Workers use DB polling — ADR-0018).
*   **Does NOT** use Redis Streams or Consumer Groups — only SET/GET + Pub/Sub.

## 9. References

*   [ADR-0017](../adr/0017-service-state-management.md) — Desired vs. Actual State
*   [ADR-0019](../adr/0019-unified-service-infrastructure.md) — Heartbeat schema
*   [Messaging Patterns](../arch/messaging_patterns.md) — Redis usage §3, Read+Subscribe §4
*   [Glossary](../glossary.md) — canonical definitions
*   [ROADMAP.md](../../ROADMAP.md) — milestone (v0.2.0)
