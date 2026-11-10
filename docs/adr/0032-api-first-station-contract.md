# ADR-0032: API-First Station Contract

> **Status:** Proposed • **Date:** 2026-11-10

## 1. Context & Problem

Four attempts at a user interface exist — `web-mock`, `webtest` and two archived stands. Each renders HTML on the server and reads the database, Redis and the filesystem directly. None has a JSON API, so:

*   every attempt was bound to the tables, Redis keys and paths of its day and was rebuilt when they changed;
*   a fleet server, a script or a home-automation system has nothing to talk to;
*   replacing a part of the core (another database engine, a service rewritten in another language) would break the interface again.

The product goal is a station that a hobby user runs alone, that a fleet server can manage by the thousand, and whose core may still change. All three need the same thing: one stable way to read and change a station.

## 2. Decision

**We chose:** one versioned HTTP API, `/api/v1`, as the only way any client reads or changes a station, defined by an OpenAPI 3.1 document that is the contract.

**Reasoning:**

*   **One contract, every client.** The dashboard ([ADR-0036](0036-svelte-spa-frontend.md)), the fleet, scripts and third-party tools use the same API. No client reads the database, Redis or the filesystem. The DB-Viewer stays a development tool.
*   **Domain terms, not storage.** Resources are what a user means — recording, detection, species, microphone, module — never a table, a Redis key or a path. Media is a URL. A storage engine or a service can then be replaced behind the API, one part at a time, without a client noticing.
*   **The document is the contract.** [`docs/api/openapi.yaml`](../api/openapi.yaml) is a hand-written draft today. Once the `api` service exists, the file is generated from it and committed; the Pydantic schemas in `silvasonic.core.schemas` stay the owner of every shape (AGENTS.md §8). The gate rejects a commit whose generated document differs from the committed one, and one that breaks compatibility with `main`. Contract tests run the document against a running implementation — the Python one now, any later one unchanged.
*   **Additive within a major version.** `/api/v1` gains operations, optional fields and enum values; nothing is renamed or removed without `/api/v2`. Clients tolerate unknown fields and enum values.
*   **Reserved shapes.** The draft is larger than the first implementation. Each operation is marked `core` or `planned`; planned operations fix the name and shape of features whose backend does not exist yet (weather, live audio, bat detection, updates), so they fit when they arrive. `GET /info` tells a client what a station supports.
*   **Server-Sent Events for live data.** Status, new detections and alerts flow one way. SSE reconnects by itself, resumes with `Last-Event-ID`, passes every proxy and carries the session cookie.
*   **The fleet reuses the schemas.** A fleet server serves the same resources under `/api/v1/stations/{station_id}/…`, and a station reports to it in the same representations. This is why identifiers are unique across stations ([ADR-0033](0033-unified-naming-and-global-identifiers.md)).

The API is a new Tier 1 service, `api` ([planned service](../services/api.md)). It reads the database and Redis, writes desired state and sends the Reconcile-Nudge (ADR-0017 is unchanged), and serves media read-only (Consumer Principle). Controller, Processor and the analysis workers get no HTTP API of their own. The conventions of the contract — naming, paging, errors, concurrency — are stated once, in the description of the OpenAPI document.

## 3. Options Considered

*   **Server-rendered pages reading the database (ADR-0003 as planned):** Rejected. It is the approach of all four attempts; it serves one client only and ties it to the storage.
*   **HTML fragments next to a JSON API:** Rejected. Two interfaces to the same data, of which only one is tested by other clients.
*   **GraphQL:** Rejected. A client can compose queries of unbounded cost, which a Raspberry Pi cannot afford; media and event streams need plain HTTP anyway; the clients and their queries are known.
*   **gRPC / Connect:** Rejected. Browsers need a translating proxy, and a hobby user cannot explore it with `curl`.
*   **Hand-written OpenAPI as the permanent source:** Rejected. It would duplicate the Pydantic schemas; a generated, committed and gate-checked file gives the same review visibility without the second owner.
*   **Generated documentation without a committed file:** Rejected. A breaking change would not show in a diff, and a rewrite in another language would have no artifact to be measured against.
*   **WebSocket for live data:** Rejected. Nothing flows from the browser to the station over it; reconnection and resumption would be ours to write.

## 4. Consequences

*   **Positive:**
    *   The dashboard no longer breaks when the core changes; parts of the core can be replaced behind the contract.
    *   Fleet, scripts and integrations get the interface the dashboard is built on, not a second-class one.
    *   "Does it still fulfil the contract?" is a test, not a review question.
*   **Negative:**
    *   A feature starts with contract work before any code.
    *   The API needs state the backend does not keep yet: events and alerts, an audit log, deletion timestamps, review state of detections ([ADR-0033](0033-unified-naming-and-global-identifiers.md)).
    *   Statistics that the old interfaces computed ad hoc become defined aggregations that must stay cheap as data grows.
*   **On acceptance these documents change:** `docs/services/web_interface.md` (data access, migration path), `docs/arch/messaging_patterns.md` (the API is the subscriber of the Read+Subscribe Pattern), `docs/arch/port_allocation.md`, `docs/glossary.md`, `AGENTS.md` §5.
