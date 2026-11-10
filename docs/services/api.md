# API

> **Status:** planned - Not implemented · **Tier:** 1 · **Instances:** Single

> [!WARNING]
> **Docs-as-Code Trap:**
> This is a temporary **Planning Document**. When the service is implemented, do **NOT** copy this file into the source code as its `README.md`!
> Instead, strictly follow the format in `../../services/_template_readme.md` and the rules in `docs/STRUCTURE.md`. Once implemented, this file must be replaced by an abstract link-stub.

**TO-BE:** The one HTTP service through which the dashboard, a fleet server and any other client read and change a station. It implements the [Station API contract](../api/index.md). Depends on [ADR-0032](../adr/0032-api-first-station-contract.md) to [ADR-0035](../adr/0035-https-and-certificates.md), all *Proposed*.

---

## 1. The Problem / The Gap

*   Every interface so far read the database, Redis and the filesystem directly and broke when they changed.
*   A fleet server, a script or a home-automation system has no interface at all.
*   Nothing authenticates a person beyond one shared Basic credential at the Gateway.

## 2. User Benefit

*   One address answers every question about the station and accepts every change, for people and programs alike.
*   The dashboard keeps working when the core behind it changes.
*   Accounts, roles, sessions and tokens, with a record of who did what.

## 3. Core Responsibilities

### Inputs

*   HTTP requests under `/api/v1`, routed by the Gateway.
*   Database: all domain tables (read), desired state and user-facing state (write).
*   Redis: `silvasonic:status:*` and the `silvasonic:status` and `silvasonic:logs` channels (Read+Subscribe Pattern).
*   Workspace, read-only: recordings, clips, species images.

### Processing

*   Authenticates each request (session cookie or API token) and checks its role.
*   Translates storage into the resources of the contract: paths become URLs, heartbeats become component states, rows become recordings and detections.
*   Computes the defined aggregations (timeline, heatmap, coverage, storage forecast).
*   Derives alerts from status and thresholds; raises and resolves them.
*   Validates every write against the contract before it reaches the database.

### Outputs

*   JSON responses, audio and images, and two Server-Sent Event streams (events, logs).
*   Database writes: desired state (`microphones`, `modules`, `settings`), review state of detections, `users`, `sessions`, `api_tokens`, `events`, `alerts`, `audit_log`.
*   `PUBLISH silvasonic:nudge "reconcile"` after a write to desired state (ADR-0017).

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                             |
| ---------------- | ------------------------------------------------------------------------ |
| **Immutable**    | No — long-running HTTP service; settings are read per request            |
| **DB Access**    | Yes                                                                      |
| **Concurrency**  | Event loop (FastAPI / Uvicorn)                                           |
| **State**        | Stateless — sessions, tokens and events live in the database             |
| **Privileges**   | Rootless; no Podman socket, no device access                             |
| **Resources**    | Low — I/O bound; media is streamed from disk, never loaded into memory   |
| **QoS Priority** | Expendable relative to the Recorder (ADR-0020); a failed API never stops recording |

## 5. Configuration & Environment

| Variable / Mount                                   | Description                         | Default / Example |
| -------------------------------------------------- | ----------------------------------- | ----------------- |
| `SILVASONIC_API_PORT`                              | API port, internal to the network   | `8000`            |
| `${SILVASONIC_WORKSPACE_PATH}/recorder:ro,z`       | Recordings (Consumer Principle)     | —                 |
| `${SILVASONIC_WORKSPACE_PATH}/birdnet:ro,z`        | Clips and species images            | —                 |

Port `8000` is the one reserved for the Web-Interface, which no longer runs a process of its own ([ADR-0036](../adr/0036-svelte-spa-frontend.md)).

## 6. Technology Stack

*   **Framework:** FastAPI on the `ServiceContext` lifespan, Pydantic schemas from `silvasonic.core.schemas`.
*   **Credentials:** `argon2-cffi` for password hashing.
*   **Contract tooling:** generated OpenAPI document, checked for drift and for breaking changes in the gate.

## 7. Open Questions & Future Ideas

*   Which aggregations need precomputed tables once a station holds a year of detections.
*   How long events and audit entries are kept, and whether the Janitor prunes them.
*   Whether the fleet agent is part of this service or a service of its own.
*   Web Push for alerts needs keys and an outbound connection; where they live.

## 8. Out of Scope

*   **Does NOT** start, stop or inspect containers (Controller's job).
*   **Does NOT** render HTML; the dashboard is a static application served by the Gateway.
*   **Does NOT** terminate TLS (Gateway's job).
*   **Does NOT** touch audio capture; recording continues when the API is down.

## 9. References

*   [Station API contract](../api/index.md)
*   [ADR-0032](../adr/0032-api-first-station-contract.md) — API-First Station Contract
*   [ADR-0033](../adr/0033-unified-naming-and-global-identifiers.md) — Unified Naming and Global Identifiers
*   [ADR-0034](../adr/0034-authentication-and-authorization.md) — Authentication and Authorization
*   [ADR-0017](../adr/0017-service-state-management.md) — Service State Management
*   [User Stories — API](../user_stories/api.md) · [User Stories — Dashboard](../user_stories/dashboard.md)
