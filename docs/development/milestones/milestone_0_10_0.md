# Milestone v0.10.0 — Station API

> **Target:** v0.10.0 — One versioned HTTP API as the only way any client reads or changes a station, with authentication and roles
>
> **Status:** ⏳ Planned (contract drafted)
>
> **References:** [ADR-0032](../../adr/0032-api-first-station-contract.md), [ADR-0034](../../adr/0034-authentication-and-authorization.md), [ADR-0017](../../adr/0017-service-state-management.md), [ADR-0019](../../adr/0019-unified-service-infrastructure.md), [ADR-0022](../../adr/0022-live-log-streaming.md), [Station API contract](../../api/index.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)
>
> **User Stories:** [API Stories](../../user_stories/api.md)

---

## Overview

The Web-Interface (v0.11.0), scripts and a future fleet server all talk to the station through `/api/v1`, defined by the OpenAPI document in [`docs/api/`](../../api/index.md). No client reads the database directly any more. The API service authenticates every request itself; a station ships without credentials.

The API is also the new reader of service status and logs. Before it is built on Redis, ADR-0041 decides whether the station keeps Redis at all: status as one file per service in a tmpfs runtime directory instead (mtime is freshness, inotify the live push), logs as size-bounded files beside it. `web-mock`, the only other Redis reader, goes with v0.11.0.

### Prerequisites

| Milestone  | Feature                                     |
| ---------- | ------------------------------------------- |
| **v0.9.0** | Station Data Foundation (schema, migrations) |

---

## Phase 1: Decisions

### Tasks

- [ ] Accept or reject ADR-0032 (API-first station contract)
- [ ] Accept or reject ADR-0034 (authentication and authorization)
- [ ] ADR-0041: service status and logs without Redis; on acceptance it amends ADR-0017, ADR-0019 and ADR-0022

---

## Phase 2: API Service

**Goal:** A Tier 1 `api` service that serves the contract and nothing else.

### Tasks

- [ ] Scaffold the service following the [Service Blueprint](../service_blueprint.md)
- [ ] The OpenAPI document is the source of truth; contract tests check the service against it
- [ ] Endpoints for the stories in [API Stories](../../user_stories/api.md)
- [ ] Gateway routes `/api/` to the service

---

## Phase 3: Authentication & Roles (ADR-0034)

**Goal:** Every request is authenticated and authorized; nothing ships with a default password.

### Tasks

- [ ] Server-side sessions in a cookie for browsers, revocable API tokens for everything else
- [ ] Three roles, enforced per endpoint
- [ ] First-run setup creates the first administrator; the seeded user with password `1234` (`config/defaults.yml`) is removed
- [ ] Retire the Gateway's basic auth once the API authenticates

---

## Phase 4: Status & Logs without Redis (if ADR-0041 is accepted)

**Goal:** One failure mode less: no service depends on a broker for its status, and an outage of it cannot evict a Recorder.

### Tasks

- [ ] The core heartbeat writes a status file per service into the shared runtime directory; it stays the only place services publish status
- [ ] The Controller's watchdog reads the status file (mtime instead of the heartbeat timestamp, same grace period)
- [ ] The log forwarder writes one size-bounded JSONL file per service beside the status; the API reads it. Its source stays `podman logs` until ADR-0042 (v0.13.0)
- [ ] The reconcile nudge is removed; the reconciler's one-second loop picks up changes
- [ ] The `redis` container, its port and `SILVASONIC_REDIS_*` variables are removed
- [ ] Integration, system and smoke tests move from Redis keys to status files; the health reconciliation test ages the file instead of deleting a key

---

## Phase 5: Service Control

**Goal:** Tier 2 singletons are switched on and off through the API (carried over from the former v0.9.0 plan).

### Tasks

- [ ] Seed the `modules` rows for Tier 2 singletons (`birdnet`, later `batdetect`, `weather`); Tier 1 and the Recorder are not seeded
- [ ] The API writes `enabled`; the reconciler applies it within its loop (with Redis kept: plus the reconcile nudge, ADR-0017)
- [ ] Unit: the seeder writes the expected rows; the reconciler stops a module with `enabled=false`
- [ ] Integration: a fresh database contains the expected rows

---

## Out of Scope (Deferred)

| Item                               | Target Version |
| ---------------------------------- | -------------- |
| Interface on top of the API        | v0.11.0        |
| HTTPS for the API                  | v0.12.0        |
| Fleet server consuming the API     | post-v1.0.0    |
| Logs from journald instead of `podman logs` | v0.13.0 (ADR-0042) |

> **Note:** The marketing website that used to be planned as v0.10.0 is its own project, `kyellsen/silvasonic.de`; its former plan is in the history of this file.
