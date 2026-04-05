# silvasonic-web-mock

> **Tier:** 1 (Infrastructure) · **Status:** Implemented · **Port:** 8001

Development UI scaffold for the Silvasonic Web Interface. Serves the **complete UI shell** (FastAPI + Jinja2 + HTMX + Alpine.js + Tailwind CSS + DaisyUI) with mock data for most views. Uses the **real database** for Settings persistence and station identity, and **Redis** for heartbeat publishing.

## 1. The Problem / The Gap

- Iterate on UI/UX with realistic layout and interactions
- Validate the full layout: header, sidebar, main, inspector, footer console
- Serve as the **clonable base** for the real `web-interface` (v0.9.0)

When building the real web-interface, clone this service and replace `mock_data` imports route-by-route with real async DB queries. The `ServiceContext` lifespan pattern, templates, static assets, and routing transfer without modification.

## 2. User Benefit

## 3. Core Responsibilities

### Inputs
* User interaction / HTTP Requests.
### Processing
* Jinja2 Server-Side rendering with HTMX swaps.
### Outputs
* HTML payload & Tailwind CSS styling.

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                   |
| ---------------- | -------------------------------------------------------------- |
| **Immutable**    | Yes                                                            |
| **DB Access**    | Yes (Reads Settings, Station Identity)                         |
| **Concurrency**  | Uvicorn Asyncio Event Loop                                     |
| **State**        | Stateless                                                      |
| **Privileges**   | Rootless                                                       |
| **Resources**    | Low                                                            |
| **QoS Priority** | `oom_score_adj=0`                                              |

## 5. Configuration & Environment

| Variable / Mount                  | Description                                    | Default / Example    |
| --------------------------------- | ---------------------------------------------- | -------------------- |
| `SILVASONIC_WEB_MOCK_PORT`        | Internal application port                      | `8001`               |
| `SILVASONIC_REDIS_URL`            | Connection to Redis for heartbeats & Pub/Sub   | `redis://redis:6379/0` |
| `SILVASONIC_HEARTBEAT_INTERVAL_S` | Interval between Redis heartbeats              | `10.0`               |
| `POSTGRES_HOST`                   | Database hostname                              | `database`           |
| `POSTGRES_USER`                   | Database user                                  | `silvasonic`         |
| `POSTGRES_PASSWORD`               | Database password                              | `silvasonic`         |
| `POSTGRES_DB`                     | Target database name                           | `silvasonic`         |
| `SILVASONIC_API_ROOT_PATH`        | Path prefix for reverse proxy routing (FastAPI)| `/web-mock`          |

## 6. Technology Stack

The UI uses **Tailwind CSS v4 + DaisyUI v5**, compiled at build time — no CDN at runtime.

```bash
# Initial setup (once, requires Node.js):
cd services/web-mock && npm install

# Build CSS (one-shot, minified):
npm run css:build

# Watch mode (rebuilds on template/CSS changes):
npm run css:watch
```

All frontend dependencies (Alpine.js, HTMX, Geist fonts) are **vendored** in `static/js/` and `static/fonts/` — no external requests at runtime.

## 7. Out of Scope

## 8. Implementation Details (Domain Specific)
## 9. References

