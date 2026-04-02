# Web Interface

> **Tier:** 1 (Infrastructure) · **Status:** Planned — v0.9.0 · **Port:** 8000
> **Prototype:** The `web-mock` service (since v0.2.0, Port 8001) implements the full UI shell with mock data. See [web-mock README](https://github.com/kyellsen/silvasonic/blob/main/services/web-mock/README.md).

The Web-Interface is the local management console for the Silvasonic recording station. It provides a real-time system dashboard, device management, service configuration, and live audio monitoring — all from a browser, without SSH.

---

## 1. Architecture & Technology Stack

### 1.1 Core Philosophy — "Fast & Light"

The frontend follows the **"Fast & Light" philosophy** ([ADR-0003](../adr/0003-frontend-architecture.md)): Server-Side Rendering (FastAPI + Jinja2), HTMX for DOM swaps, Alpine.js for client-side interactivity.

### 1.2 Backend Stack

| Layer      | Technology                         |
| ---------- | ---------------------------------- |
| Framework  | FastAPI + Uvicorn                  |
| Templating | Jinja2                             |
| Database   | SQLAlchemy 2.0+ (async), asyncpg   |
| API Docs   | Swagger / OpenAPI (auto-generated) |

### 1.3 Frontend Stack

| Layer               | Technology          | Version |
| ------------------- | ------------------- | ------- |
| CSS Framework       | Tailwind CSS        | 4.x     |
| UI Components       | DaisyUI             | 5.x     |
| Typography          | Geist / Geist Mono  | latest  |
| Icons               | Lucide (inline SVG) | latest  |
| Data Visualization  | Apache ECharts      | 5.x     |
| Audio Visualization | Wavesurfer.js       | 7.x     |

### 1.4 State Management & Data Flow

**Read+Subscribe Pattern (Observability):**
- Status: reads `silvasonic:status:*` keys for initial state, subscribes to `silvasonic:status` channel via SSE for live updates.
- Logs: subscribes to `silvasonic:logs` channel via SSE to stream container logs into the footer console ([ADR-0022](../adr/0022-live-log-streaming.md)).

**State Reconciliation Pattern (Control):**
- The Web-Interface does **not** orchestrate containers directly.
- It writes desired state to the database, then publishes a `silvasonic:nudge` signal to Redis.
- The Controller picks up the nudge and performs the actual container lifecycle actions ([ADR-0017](../adr/0017-service-state-management.md)).

### 1.5 Operational Constraints

- **Database First, No Filesystem Scanning:** Recording and detection lists come exclusively from the database.
- **Media Serving:** The `:ro` filesystem mount serves individual known files (WAV playback, spectrogram images) by their database-recorded path only.
- **Stateless Container:** All state lives in the database and Redis. The container is freely restartable.

---

## 2. Design System

- **Theme:** Custom DaisyUI themes (`silvadark` / `silvalight`), each module has its own accent color token.
- **Typography:** Geist for UI text, Geist Mono for data values and log output.
- **Icons:** Lucide, inline SVG in Jinja2 templates.
- **Data Visualization (TO-BE):** Apache ECharts for time-series, heatmaps, histograms. Wavesurfer.js v7 with Regions plugin for BirdNET/BatDetect annotation overlay, Timeline, Minimap, pre-computed peaks.
- **Offline:** All assets bundled in the container image. No CDN at runtime.

---

## 3. UX Concept

### 3.1 Layout & Navigation

Five fixed zones: Header, Sidebar Nav, Main Content, Inspector (right), Footer. Sidebar has two groups: **System** (Dashboard, Recorders, Processor, Cloud Sync) and **Modules** (Livesound, Birds, Bats, Weather). Settings + About pinned to bottom.

> [!IMPORTANT]
> **Conditional Module Rendering:** Module sidebar entries are only visible when the corresponding module is enabled in Settings → Modules. This is DB-driven and not yet implemented in the web-mock (which shows all modules always).

### 3.2 Navigation Routing Rulebook

| Content Type                             | Pattern                    | Applies To                           |
| ---------------------------------------- | -------------------------- | ------------------------------------ |
| Hardware/Service instances (hard-limited) | **Bento-Grid → Inspector** | Recorders (max 5)                    |
| Worker results / data analyses           | **Horizontal Tabs**        | Birds, Bats, Weather                 |
| Admin subsections                        | **Horizontal Tabs**        | Settings                             |

### 3.3 Action Risk Classification

| Class                   | Badge | Mechanism                                                        |
| ----------------------- | ----- | ---------------------------------------------------------------- |
| **Safe**                | ✅     | Execute immediately (export, rename, test, browse).              |
| **Guarded**             | 🟨     | Impact preview + "Apply at next safe point" or schedule.         |
| **Forbidden while REC** | ⛔     | Button disabled + tooltip. Admin override: 2-step typed confirm. |

---

## 4. Page Blueprints

> **Implementation reference:** All pages below are prototyped in `web-mock/templates/`. The mock uses `mock_data.py`; the real interface replaces these with async DB queries route-by-route.

### 4.1 Dashboard

Bento-Grid of system function cards: Orchestration (Controller status), Data Pipeline (Processor status), SSD Storage, CPU, RAM, Uptime. Active Alerts. ECharts upload throughput chart (TO-BE).

### 4.2 Recorders (Bento-Grid, max 5)

Grid of Recorder Cards: live level bar, sample rate, channels, segment, gain, status. Detail view via click. Inspector shows Wavesurfer.js audio preview (TO-BE).

### 4.3 Processor

Single page (no tabs): Indexer file table + Retention event log. Storage & Retention configuration is managed in **Settings → Storage & Retention**.

### 4.4 Cloud Sync (Single-Target)

Single-page view: upload queue size, throughput, last sync, status, configured remote target. Replaces the former multi-target "Uploaders" Bento-Grid (KISS refactoring, v0.6.0).

### 4.5 Birds / Bats (Tabs)

`[ Discovery ] [ Analyzer ] [ Statistics ]`

Discovery: Pokédex-style species cards. Analyzer: data table with filters, row click → Inspector (Wavesurfer.js spectrogram + annotation regions, TO-BE). Statistics: ECharts dashboards (TO-BE).

### 4.6 Weather (Tabs)

`[ Overview ] [ Current ] [ Statistics ] [ Correlation ]`

ECharts time-series for temperature, precipitation, humidity, pressure, wind. Correlation: dual Y-axis — detections overlaid with weather parameters (TO-BE).

### 4.7 Settings (Tabs)

`[ General ] [ Modules ] [ Storage & Retention ] [ Remotes ] [ Network ] [ User ]`

- **Modules:** Toggle per module with system reload. Module state drives sidebar visibility.
- **Remotes:** Single-target upload configuration (Nextcloud, S3). Test Connection + Save.
- **Network:** WLAN Hotspot + Tailscale VPN status and config.
- **User:** Password management for local admin.

### 4.8 Observability (TO-BE)

`[ Metrics ] [ Events ]`

Per-service CPU/RAM/NVMe I/O charts (ECharts). Human-readable audit trail. Logs exclusively in Footer Console.

### 4.9 Maintenance (TO-BE)

`[ Updates ] [ Backup & Export ]`

Updates require REC = IDLE.

---

## 5. Migration Path: Web-Mock → Web-Interface (v0.9.0)

The `web-mock` service is the **clonable base** for this service. Migration steps:

1. **Clone:** `cp -r services/web-mock → services/web-interface`. Rename package to `silvasonic-web-interface`, update port to `8000`.
2. **Delete `mock_data.py`:** All mock data is replaced by async DB queries.
3. **Replace route-by-route:** Each route changes one line — `mock_data.X` → `await db_query(session)`. Templates, static assets, and routing remain unchanged.
4. **SSE Console:** Replace `FAKE_LOG_LINES` cycling generator with real `SUBSCRIBE silvasonic:logs` from Redis.
5. **Conditional Sidebar:** Add DB-driven module visibility (show Birds/Bats/Weather only when enabled in Settings → Modules).
6. **Retire web-mock:** Move to `profiles: ["dev"]` in compose or remove entirely.

> [!NOTE]
> The `ServiceContext` lifespan, `get_station()`, `get_settings()`, and `POST /settings/general` are **already production-ready** in the web-mock and can be kept as-is.

---

## 6. Scope Boundaries

- **No Orchestration:** Does not start or stop containers — that is the Controller's job.
- **No Media Processing:** Does not record audio, run ML inference, or process signals.
- **Internal Network Only:** Not a public API. Accessible locally or via Tailscale VPN.
- **RBAC:** Planned for v1.9.0+ (multi-user). Not in scope for v0.9.0.

---

## 7. See Also

- [ADR-0003: Frontend Architecture](../adr/0003-frontend-architecture.md)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)
- [ADR-0021: Frontend Design System](../adr/0021-frontend-design-system.md)
- [ADR-0022: Live Log Streaming](../adr/0022-live-log-streaming.md)
- [Web-Mock README](https://github.com/kyellsen/silvasonic/blob/main/services/web-mock/README.md) — living prototype
