# Milestone v0.2.0 — Service Infrastructure

> **Target:** v0.2.0 — Service Infrastructure
>
> **References:** [ADR-0019: Unified Service Infrastructure](../adr/0019-unified-service-infrastructure.md), [VISION.md](../../VISION.md), [ROADMAP.md](../../ROADMAP.md)

---

## Phase 1: Setup Redis Container

**Goal:** Provide the central status bus (Redis) as part of the Tier 1 infrastructure.

### Tasks
- [ ] Add `redis` service to `compose.yml`
  - Image: `redis:7-alpine`
  - Command: `redis-server --save "" --appendonly no` (in-memory only, no persistence needed for status bus)
  - Port: `6379` (internal to `silvasonic-net`)
- [ ] Add `redis_data` or bind mount if persistence is reconsidered (currently not recommended per ADR-0019 for status)
- [ ] Add `redis` to `depends_on` for relevant services (Controller, Web-Interface).

---

## Phase 2: Core Service Infrastructure

**Goal:** Implement the `SilvaService` base class and shared modules for the unified lifecycle.

### Tasks
- [ ] Implement `silvasonic.core.service.SilvaService` module
  - Handles canonical lifecycle: Logging config, Health Server startup, Redis connection, Heartbeat start, graceful shutdown logic.
- [ ] Implement `silvasonic.core.heartbeat.HeartbeatPublisher`
  - Async fire-and-forget Redis heartbeats to `silvasonic:status:<instance_id>` (SET + TTL) and `silvasonic:status` (PUBLISH).
- [ ] Implement `silvasonic.core.redis.get_redis_connection`
  - Best-effort connection with auto-reconnect fallback mechanism.
- [ ] Update `silvasonic.core.settings` to include Redis connection string.

---

## Phase 3: Migrate Existing Services

**Goal:** Migrate previously implemented Python services to use `SilvaService`.

### Tasks
- [ ] Update `controller/__main__.py` to use `SilvaService`
- [ ] Update `recorder/__main__.py` to use `SilvaService`
- [ ] Remove duplicate/custom health/shutdown logic from both services, relying on the base class.
- [ ] Verify both services publish status heartbeats correctly (via log output or Redis CLI).
- [ ] Ensure integration tests and smoke tests (`just check-all`) pass with the new infrastructure.
