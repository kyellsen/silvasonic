# ADR-0022: Live Log Streaming — Podman Logs via Redis SSE

> **Status:** Accepted • **Date:** 2026-02-23

## 1. Context & Problem

The Web-Interface needs to display real-time container logs for debugging and monitoring purposes. Users should be able to observe service activity (e.g., "BirdNET analysis running...", "Recorder started for ultramic-01") directly in the browser without SSH access.

The existing [Messaging Patterns](../arch/messaging_patterns.md) define Redis for exactly **two** purposes:
1.  `SET silvasonic:status:<id>` with TTL — current status snapshot.
2.  `PUBLISH silvasonic:status` — live status updates.

Adding a log stream introduces a **third** Redis channel, expanding the system's Redis usage beyond the original specification.

## 2. Decision

**We chose:** Stream container logs from Podman via Redis Pub/Sub to the Web-Interface using Server-Sent Events (SSE).

**Architecture:**

```
┌─────────────────────────────────────────────────────────────────┐
│  Live Log Streaming                                             │
│                                                                 │
│  1. Service ──[structlog JSON]──► stdout                        │
│  2. Controller ──[podman logs --follow]──► reads stdout          │
│  3. Controller ──[PUBLISH silvasonic:logs]──► Redis              │
│  4. Web-Interface ──[SUBSCRIBE silvasonic:logs]──► SSE endpoint  │
│  5. Browser ──[hx-ext="sse"]──► Alpine.js auto-scroll terminal  │
└─────────────────────────────────────────────────────────────────┘
```

**Log payload schema** (structlog JSON):

```json
{
  "service": "birdnet",
  "instance_id": "birdnet",
  "level": "info",
  "message": "Analysis complete: 42 detections in recording-2026-02-23T03-00.wav",
  "timestamp": "2026-02-23T03:15:42Z"
}
```

**Reasoning:**
*   **Minimal Redis extension:** One additional `PUBLISH` channel. No Streams, no Consumer Groups. The log channel follows the same fire-and-forget pattern as status updates.
*   **structlog consistency:** All services already use structlog with JSON output (AGENTS.md §5). Log payloads reuse the existing structured format.
*   **SSE delivery:** The Web-Interface already uses HTMX SSE for status updates. Log streaming uses the same mechanism — no new transport layer.
*   **Best-effort:** Like status heartbeats, log messages are fire-and-forget. If the Web-Interface is not connected, logs are simply not displayed. No log persistence in Redis (no backpressure risk).

> [!IMPORTANT]
> This amends [Messaging Patterns §3](../arch/messaging_patterns.md): Redis now serves **three** purposes (Status SET, Status PUBLISH, Logs PUBLISH).

## 3. Options Considered

*   **File tailing endpoint (FastAPI streaming `/var/log`):** Rejected.
    *   Requires filesystem access to container log directories, which breaks container isolation.
    *   Fragile path management across different container runtimes.

*   **Direct Podman API exposure:** Rejected.
    *   Exposes the container management API to the browser — unacceptable security risk.
    *   Violates the principle that only the Controller interacts with Podman.

*   **Logs only via SSH:** Rejected.
    *   Defeats the core purpose of the Web-Interface: no SSH required for station management.

*   **Redis Streams (instead of Pub/Sub):** Rejected.
    *   Adds persistence and consumer group complexity that is unnecessary for ephemeral log display.
    *   Violates the "Minimal Redis" principle — Pub/Sub fire-and-forget is sufficient.

## 4. Consequences

*   **Positive:**
    *   Real-time log visibility from the browser — no SSH needed.
    *   Reuses existing infrastructure (Redis Pub/Sub, SSE, Alpine.js).
    *   Consistent with the fire-and-forget pattern already established for heartbeats.
    *   Controller remains the single point of Podman interaction (no API exposure).

*   **Negative:**
    *   Redis usage expanded from 2 to 3 purposes — increases Redis channel count by one.
    *   Log messages are ephemeral — if the browser is not connected, logs are lost (acceptable for a monitoring dashboard; persistent logs remain in Podman/journalctl).
    *   Controller takes on additional responsibility (log forwarding), slightly increasing its complexity.

## See Also

*   [Messaging Patterns](../arch/messaging_patterns.md) — Amended: three Redis purposes (§3)
*   [ADR-0019: Unified Service Infrastructure](0019-unified-service-infrastructure.md) — structlog JSON format
*   [Web-Interface Service Specification](../services/web_interface.md) — Live log display
