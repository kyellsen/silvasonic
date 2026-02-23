# Web Interface

> **Tier:** 1 (Infrastructure) · **Status:** Planned — v0.8.0 · **Port:** 8000

The Web-Interface is the local management console for the Silvasonic recording station. It provides a real-time system dashboard, device management, service configuration, and live audio monitoring — all from a browser, without SSH.

---

## 1. Architecture & Technology Stack

### 1.1 Core Philosophy — "Fast & Light"

The frontend follows the **"Fast & Light" philosophy** ([ADR-0003](../adr/0003-frontend-architecture.md)). It uses a **Modern Monolith** (server-side rendering) instead of a Single-Page Application:

- **Server-Side Rendering (SSR):** FastAPI + Jinja2 generates HTML server-side.
- **HTMX:** Dynamic DOM swaps over the network — no full page reloads.
- **Alpine.js:** Lightweight client-side state for interactivity (modals, toggles, sidebar collapse).

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

- **Database First, No Filesystem Scanning:** Recording and detection lists come exclusively from the database. `os.listdir` / `scandir` is forbidden.
- **Media Serving:** The `:ro` filesystem mount serves individual known files (WAV playback, spectrogram images) by their database-recorded path only.
- **Stateless Container:** All state lives in the database and Redis. The container itself is stateless and freely restartable.
- **Rootless:** Runs as a fully unprivileged container.

---

## 2. UI/UX & Design System

### 2.1 Design Principles

- **IDE-Style Dashboard:** Dark mode, data-dense layouts, "Modern Soft-SaaS" aesthetic.
- **Pure CSS Components:** DaisyUI provides semantic class names (`btn`, `card`, `table`) with zero JavaScript — HTMX DOM swaps work without re-initialization.
- **Custom Theme:** All accent colors defined via DaisyUI's CSS Custom Property theme system. Each page and module has its own accent color; exact tokens are defined in the theme config.
- **Offline Production:** All assets (fonts, icons, compiled CSS) are bundled in the container image. Development uses CDN for rapid iteration.

### 2.2 Typography

- **UI Text:** Geist — headings, labels, navigation, body copy.
- **Data & Code:** Geist Mono — log lines, confidence values, timestamps, spectrogram axis labels. Tabular figures for column alignment.

### 2.3 Iconography

Lucide Icons — implemented as inline `<svg>` elements in Jinja2 templates. No icon font, no FOUT, stroke-width aligns with DaisyUI's rounded aesthetic.

### 2.4 Data & Media Visualization

- **Apache ECharts:** Canvas/WebGL rendering for time-series, heatmaps, histograms, and linked zoom/pan charts.
- **Wavesurfer.js v7:** Audio waveform + spectrogram rendering. Plugins used: Regions (BirdNET/BatDetect annotation overlay), Timeline, Minimap. Supports pre-computed peaks for instant load of long recordings.

---

## 3. UX Concept

### 3.1 Layout Zones

The interface uses five fixed zones:

```
┌──────────────────────────────────────────────────────────┐
│  HEADER: [☰] [Logo] [Station Name] | [●REC 2 · ☁1] | [🌙][⬛][👤][⚙]
├────────┬─────────────────────────────────────┬───────────┤
│        │                                     │           │
│  NAV   │         MAIN VIEW                   │ INSPECTOR │
│        │   (Bento-Grid or Tab content)        │  (right)  │
│        │                                     │           │
├────────┴─────────────────────────────────────┴───────────┤
│  FOOTER: [● N Alerts · NVMe 68% · 🌡51°C · last event]  [▲Console]
└──────────────────────────────────────────────────────────┘
```

| Zone          | Purpose                                                                                                                          |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **Header**    | Instance counts only (`● REC 2 · ☁ 1`). Nav toggle, dark mode, inspector toggle, profile, settings.                              |
| **Navigator** | Flat sidebar — top-level context switcher. No nested dropdowns. Settings + About pinned to bottom.                               |
| **Main View** | Content area — Bento-Grid or horizontal Tabs depending on content type (see §3.2).                                               |
| **Inspector** | Right-side panel. Opens on item click. Shows rich details, audio/spectrogram, config, actions. Raw data only via export buttons. |
| **Footer**    | System health strip (NVMe, CPU temp, alerts, last event) + Console toggle.                                                       |

### 3.2 Navigation Structure

```
SYSTEM
  ◉ Dashboard
  🎙 Recorders
  ⚙  Processor
  📤 Uploaders

MODULES  ←— conditionally rendered (DB-driven)
  🐦 Birds        (only if BirdNET enabled)
  🦇 Bats         (only if BatDetect enabled)
  🌦 Weather      (only if Weather enabled)

────────────────  (pinned to bottom)
  ⚙  Settings
  ℹ  About Silvasonic
```

### 3.3 Navigation Routing Rulebook

Navigation pattern is determined by the **nature of the content**:

| Content Type                              | Pattern                    | Applies To                           |
| ----------------------------------------- | -------------------------- | ------------------------------------ |
| Hardware/Service instances (hard-limited) | **Bento-Grid → Inspector** | Recorders (max 5), Uploaders (max 3) |
| Worker results / data analyses            | **Horizontal Tabs**        | Birds, Bats, Weather                 |
| Admin subsections                         | **Horizontal Tabs**        | Settings, Observability, Maintenance |

### 3.4 Footer Console

The **only** place to view service logs. One service at a time — never mixed:

```
Service: [ recorder#1 ▾ ]       [⏸] [↓] [✕]
─────────────────────────────────────────────
17:43:12 INFO  segment written: rec_001.wav
17:43:15 WARN  dropped frames: 3
```

Selecting a service switches the SSE subscription server-side. Logs are fire-and-forget (no history stored in the UI).

### 3.5 Action Risk Classification

| Class                   | Badge | Mechanism                                                        |
| ----------------------- | ----- | ---------------------------------------------------------------- |
| **Safe**                | ✅     | Execute immediately (export, rename, test, browse).              |
| **Guarded**             | 🟨     | Impact preview + "Apply at next safe point" or schedule.         |
| **Forbidden while REC** | ⛔     | Button disabled + tooltip. Admin override: 2-step typed confirm. |

---

## 4. Page Blueprints

### 4.1 Dashboard

Real-time operations overview. System function cards (always visible):
- **Orchestration** (Controller): reconcile status, active containers, pending changes.
- **Data Pipeline** (Processor): index freshness, ingestion backlog, janitor status.

Compact ECharts: NVMe trend, CPU temp, upload throughput. Active Alerts card. Recent Events timeline.

### 4.2 Recorders (Bento-Grid, max 5)

Grid of Recorder Cards. Each card: live level bar, sample rate, segment info, status dot.

**Inspector:** Wavesurfer.js audio preview. Guarded config: gain, channel, sample rate. Actions: Test (Safe) · Apply at next segment (Guarded) · Restart (Forbidden while REC).

### 4.3 Processor (Tabs)

`[ Pipeline ] [ Storage & Retention ] [ Index ]`

Janitor UX: all deletion is policy-driven here only. Impact preview required. Pinned items override janitor.

### 4.4 Uploaders (Bento-Grid, max 3)

Grid of Uploader Cards: queue size, throughput, last sync, throttle state.

**Inspector:** Target type, auth, bandwidth throttling, schedule windows. Actions: Test · Sync Now · Pause · Re-Auth.

### 4.5 Birds / Bats (Tabs)

`[ Discovery ] [ Analyzer ] [ Statistics ]`

- **Discovery:** Pokédex-style species cards (image, names, count).
- **Analyzer:** Data table with filters (species, time range, mic, confidence). Row click → Inspector (Wavesurfer.js spectrogram + BirdNET/BatDetect annotation regions + export buttons).
- **Statistics:** ECharts dashboards (detections/day, confidence histogram, per-mic breakdown).

### 4.6 Weather (Tabs)

`[ Current ] [ Correlations ] [ Export ]`

Correlations: ECharts dual Y-axis — detections over time overlaid with weather parameters.

### 4.7 Settings (Tabs)

`[ General ] [ Modules ] [ Recording Policy ] [ Network ] [ Access ] [ Integrations ]`

- **Modules:** Toggle per module with Impact Preview. Apply now or scheduled. Module state toggles drive sidebar visibility via DB → Controller → HTMX sidebar refresh.
- **Access:** Password, session management, Tailscale node info, API keys.

### 4.8 Observability (Tabs)

`[ Metrics ] [ Events ]`

Metrics: per-service CPU/RAM/NVMe I/O (ECharts). Events: human-readable audit trail. Logs are exclusively in the footer Console.

### 4.9 Maintenance (Tabs)

`[ Updates ] [ Backup & Export ]`

Updates require REC = IDLE. Storage & Retention control lives in Processor (§4.3).

---

## 5. Scope Boundaries

- **No Orchestration:** Does not start or stop containers — that is the Controller's job.
- **No Media Processing:** Does not record audio, run ML inference, or process signals.
- **Internal Network Only:** Not a public API. Accessible locally or via Tailscale VPN.
- **RBAC:** Planned for v1.9.0+ (multi-user). Not in scope for v0.8.0.

---

## 6. See Also

- [ADR-0003: Frontend Architecture](../adr/0003-frontend-architecture.md)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)
- [ADR-0021: Frontend Design System](../adr/0021-frontend-design-system.md)
- [ADR-0022: Live Log Streaming](../adr/0022-live-log-streaming.md)
