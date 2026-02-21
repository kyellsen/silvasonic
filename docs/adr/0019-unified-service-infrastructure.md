# ADR-0019: Unified Service Infrastructure — SilvaService Pattern

> **Status:** Accepted • **Date:** 2026-02-21

## 1. Context & Problem

Silvasonic consists of 13 services across two tiers. Each service needs:

*   Health monitoring (HTTP endpoint for Podman probes)
*   Status reporting (Redis heartbeat for Web-Interface)
*   Structured logging
*   Graceful shutdown (SIGTERM/SIGINT)
*   Pydantic-based configuration

Without a unified pattern, each service implements these concerns independently, leading to inconsistency, code duplication, and higher maintenance cost. The risk grows as the service count increases from the current 3 (database, controller, recorder) to the planned 13.

## 2. Decision

**We chose:** A `SilvaService` base class in `silvasonic.core.service` that provides the canonical lifecycle for every Python service.

### 2.1. Service Classification

| Category           | Services                                                   | Behavior at Runtime                                                                                 |
| ------------------ | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **Immutable**      | Recorder, Uploader, BirdNET, BatDetect, Weather, Processor | Config injected at start (env vars / DB read on init). No runtime commands. Restart to reconfigure. |
| **Mutable**        | Controller, Web-Interface                                  | Maintain and change state at runtime. React to events and user input.                               |
| **Infrastructure** | Database, Redis, Gateway, Icecast, Tailscale               | External services managed by Compose/Quadlets. Not Python services.                                 |

> [!NOTE]
> The Processor is classified as **immutable** despite being Tier 1. Its behavior (polling interval, retention thresholds) is configured at startup. Changing these parameters requires a container restart — identical to the Recorder pattern.

### 2.2. Unified Lifecycle

Every Python service follows this exact sequence:

```python
async def main() -> None:
    service = SilvaService(
        name="recorder",
        instance_id="ultramic-01",  # Singletons: instance_id = name
        port=9500,
    )

    # 1. Logging — MUST be first
    service.configure_logging()

    # 2. Health Server — HTTP /healthy on :port (Podman/Compose probes)
    service.start_health_server()

    # 3. Redis Connection — best-effort, non-blocking
    #    If Redis is unreachable: logs warning, continues without heartbeat
    await service.connect_redis()

    # 4. Heartbeat Loop — fire-and-forget, every 10 seconds
    #    Two Redis operations per heartbeat (both with 50ms timeout):
    #      SET silvasonic:status:<instance_id> <payload> EX 30
    #      PUBLISH silvasonic:status <payload>
    service.start_heartbeat()

    # 5. Service-specific logic (override)
    await record_audio()

    # 6. Graceful Shutdown — SIGTERM + SIGINT
    await service.wait_for_shutdown()
```

### 2.3. Two Independent Health Channels

Every service exposes health via **two channels** that read from the **same** `HealthMonitor` singleton:

| Channel         | Transport                      | Consumer       | Purpose                                                   |
| --------------- | ------------------------------ | -------------- | --------------------------------------------------------- |
| HTTP `/healthy` | HTTP (synchronous)             | Podman/Compose | Container orchestration: "should this container restart?" |
| Redis Heartbeat | Redis (async, fire-and-forget) | Web-Interface  | Application status: "what is this service doing?"         |

> [!IMPORTANT]
> HTTP health is mandatory — Podman healthchecks require HTTP. Redis heartbeats are the best-effort complement for rich, push-based, aggregated status. These are not redundant channels; they serve different consumers with different requirements.

### 2.4. Heartbeat Payload Schema

All heartbeats use the same JSON schema:

```json
{
  "service": "recorder",
  "instance_id": "ultramic-01",
  "timestamp": 1706612400.123,
  "health": {
    "status": "ok",
    "components": {
      "recording": { "healthy": true, "details": "" },
      "disk_space": { "healthy": true, "details": "82% free" }
    }
  },
  "activity": "recording",
  "meta": { "db_level": -45.2 }
}
```

### 2.5. New Core Modules

| Module                      | Purpose                                                        | Used By      |
| --------------------------- | -------------------------------------------------------------- | ------------ |
| `silvasonic.core.service`   | `SilvaService` base class — canonical lifecycle                | All services |
| `silvasonic.core.heartbeat` | `HeartbeatPublisher` — async fire-and-forget Redis heartbeats  | All services |
| `silvasonic.core.redis`     | `get_redis_connection()` — best-effort connect, auto-reconnect | All services |

These extend the existing shared modules:

| Module (existing)                            | Purpose                                        |
| -------------------------------------------- | ---------------------------------------------- |
| `silvasonic.core.health.HealthMonitor`       | Thread-safe singleton for component status     |
| `silvasonic.core.health.start_health_server` | Background HTTP server on `/healthy`           |
| `silvasonic.core.logging.configure_logging`  | Structured logging (Rich in dev, JSON in prod) |
| `silvasonic.core.settings.DatabaseSettings`  | Pydantic-based config from env vars            |

## 3. Options Considered

*   **No base class (copy-paste lifecycle):** Rejected. Already causing drift between controller and recorder implementations. Maintenance cost grows with each new service.
*   **Framework-based approach (e.g., Nameko, FastStream):** Rejected. Adds a heavy runtime dependency for a simple lifecycle pattern. Silvasonic services are not complex enough to warrant a framework.
*   **Recorder without Redis (Controller proxies status):** Rejected. Creates a non-uniform pattern. The Controller would need to poll Recorder health via HTTP and re-publish to Redis — adding latency, code, and a different status path for Tier 2 vs. Tier 1 services.

## 4. Consequences

*   **Positive:**
    *   **Uniform:** Every service follows the same lifecycle, reports status the same way, and shuts down the same way.
    *   **Minimal code per service:** New services only implement their domain logic — health, heartbeat, logging, and shutdown are inherited.
    *   **Testable:** The `SilvaService` base class can be unit-tested once; individual services test only their overrides.
    *   **Redis dependency is lightweight:** `redis-py` is ~60 KB pure Python. Fire-and-forget heartbeats add negligible overhead.
*   **Negative:**
    *   `redis-py` becomes a transitive dependency for all services, including the Recorder.
    *   Services cannot be tested in complete isolation from Redis (though the heartbeat silently degrades if Redis is unavailable).
    *   The `SilvaService` abstraction must remain thin — feature creep in the base class would affect all services.
