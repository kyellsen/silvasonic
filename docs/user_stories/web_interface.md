# User Stories — Web Interface

> **Service:** Web-Interface · **Tier:** 1 (Infrastructure) · **Status:** Planned (since v0.8.0)
>
> **Prototype:** The [web-mock](../../services/web-mock/README.md) service (since v0.2.0) implements the complete UI shell with mock data and serves as a **living UX specification**. All page layouts, navigation patterns, and interaction flows are prototypically implemented there — they are more illustrative than prose descriptions.
>
> **UX Concept:** [docs/services/web_interface.md](../services/web_interface.md) — Layout, Routing Rulebook, Action Risk Classification, Page Blueprints, Migration Path.

> [!NOTE]
> **Intentionally few stories:** Page-specific UX requirements (dashboard widgets, recorder cards, species lists, etc.) are specified by the Web-Mock prototype and the [Page Blueprints](../services/web_interface.md#4-page-blueprints). Functional requirements for data display are in the respective service user stories (e.g., [US-C05](./controller.md#us-c05), [US-P04](./processor.md#us-p04), [US-U05](./uploader.md#us-u05), [US-B02](./birdnet.md#us-b02)). This document describes only **cross-cutting UI behavior** that is not apparent from the prototype or the service stories.

---

## US-WI01: Login & Access Control 🔐

> **As a user**
> **I want to** be required to log in to the web interface with a username and password,
> **so that** unauthorized persons on the same network have no access to my recordings and settings.

### Acceptance Criteria

#### Login Flow
- [ ] All pages require an active session — without login, users are redirected to the login page.
- [ ] Login form: username + password, validation against `users` table (bcrypt hash, [US-C08](./controller.md#us-c08)).
- [ ] After successful login: redirection to the last visited page (or Dashboard by default).
- [ ] Logout button in the sidebar (below Settings/About).

#### Session Management
- [ ] Sessions are managed server-side (no JWT — Silvasonic is single-node, not a distributed system).
- [ ] Session timeout after configurable inactivity time (default: 24 hours).
- [ ] On session expiration: automatic redirect to the login page with a notice.

#### Security
- [ ] Brute-force protection: max 5 failed attempts, then 30 seconds lockout.
- [ ] Password change via Settings → User ([Page Blueprint §4.7](../services/web_interface.md#47-settings-tabs)).
- [ ] The default password from the initial setup ([US-C08](./controller.md#us-c08)) is marked as requiring a change.

### Non-Functional Requirements

- Logging in must have **no impact** on running recordings — the web interface is purely an observation and control tool.
- Exception: Health endpoint (`/healthy`) remains accessible **without** authentication.

### Milestone

- **Milestone:** v0.8.0

### References

- [Web-Interface Service Docs §Settings → User](../services/web_interface.md#47-settings-tabs)
- [Controller User Stories — US-C08: Works immediately after installation](./controller.md#us-c08)
- [Gateway User Stories — US-GW03: Station protected against unauthorized access](./gateway.md#us-gw03)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)

---

## US-WI02: Real-time status without reloading 🔄

> **As a user**
> **I want** the system status (recorder states, metrics, alerts) to update live without having to reload the page,
> **so that** I can assess the current state of my station at a glance at any time.

### Acceptance Criteria

#### Live Updates
- [ ] All status widgets (Dashboard cards, Sidebar badges, Recorder status, Alerts) update in real-time via Server-Sent Events (SSE).
- [ ] The SSE endpoint initially delivers the complete state (`silvasonic:status:*` keys from Redis) and thereafter only deltas (`SUBSCRIBE silvasonic:status`).
- [ ] HTMX-based DOM swaps ensure fluid updates without full-page reloads.

#### Resilience
- [ ] On connection loss (e.g., Wi-Fi change), the client automatically tries to restore the SSE connection.
- [ ] During reconnection, a visual indicator is shown (e.g., "Connection lost…").
- [ ] If Redis temporarily fails, the UI shows the last known state — no blank screen.

#### Footer Console (Live Logs)
- [ ] The Web-Mock prototype ([SSE Console](../../services/web-mock/README.md)) is replaced by real Redis `SUBSCRIBE silvasonic:logs` ([ADR-0022](../adr/0022-live-log-streaming.md)).
- [ ] Log messages are filterable by service, with auto-scroll and pause functionality.

### Milestone

- **Milestone:** v0.8.0

### References

- [Web-Interface Service Docs §1.4: State Management & Data Flow](../services/web_interface.md#14-state-management--data-flow)
- [Web-Mock SSE Console](../../services/web-mock/src/silvasonic/web_mock/__main__.py) — Prototype implementation
- [ADR-0019: Unified Service Infrastructure §Heartbeat](../adr/0019-unified-service-infrastructure.md)
- [ADR-0022: Live Log Streaming](../adr/0022-live-log-streaming.md)
- [Controller User Stories — US-C09: Live service logs in browser](./controller.md#us-c09)
- [Controller User Stories — US-C05: System status in dashboard](./controller.md#us-c05)

---

## US-WI03: Show only enabled modules 📦

> **As a user**
> **I want** only the modules I have actually enabled (e.g., Birds, Bats, Weather) to be visible in the navigation,
> **so that** the interface remains clean and doesn't distract me with features I don't use.

### Acceptance Criteria

- [ ] Module entries in the sidebar (Birds, Bats, Weather, Livesound) are only displayed if the corresponding module is activated in Settings → Modules.
- [ ] Activation status is read from the database (`system_services` table, `enabled` flag).
- [ ] If a module is enabled/disabled, the sidebar updates **without a page reload** (HTMX swap or SSE push).
- [ ] Accessing the URL of a disabled module (e.g., `/birds` when BirdNET is disabled) shows a friendly notice page — no 404.
- [ ] On first boot, all optional modules are disabled — only system pages (Dashboard, Recorders, Processor, Uploaders) are visible.

### Milestone

- **Milestone:** v0.8.0

### References

- [Web-Interface Service Docs §3.1: Layout & Navigation](../services/web_interface.md#31-layout--navigation)
- [Web-Mock Templates](../../services/web-mock/src/silvasonic/web_mock/templates/base.html) — Sidebar prototype (currently shows all modules)
- [Controller User Stories — US-C03: Control services via web interface](./controller.md#us-c03)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)

---

> [!NOTE]
> **UX Specification lives in code:** For all page-specific details (layouts, colors, components, interactions), the [web-mock](../../services/web-mock/README.md) is the normative reference. User Stories here solely describe **behavior** that is not apparent from the prototype.
