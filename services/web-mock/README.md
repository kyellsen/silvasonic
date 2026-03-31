# silvasonic-web-mock

> **Tier:** 1 (Infrastructure) · **Status:** Implemented · **Port:** 8001

Development UI scaffold for the Silvasonic Web Interface. Serves the **complete UI shell** (FastAPI + Jinja2 + HTMX + Alpine.js + Tailwind CSS + DaisyUI) with mock data for most views. Uses the **real database** for Settings persistence and station identity, and **Redis** for heartbeat publishing.

## Purpose

- Iterate on UI/UX with realistic layout and interactions
- Validate the full layout: header, sidebar, main, inspector, footer console
- Serve as the **clonable base** for the real `web-interface` (v0.9.0)

When building the real web-interface, clone this service and replace `mock_data` imports route-by-route with real async DB queries. The `ServiceContext` lifespan pattern, templates, static assets, and routing transfer without modification.

## CSS Development

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

## Running

```bash
# Via compose (recommended):
podman-compose up web-mock

# Directly (dev hot-reload — requires css:build first):
uv run python -m silvasonic.web_mock
```

Open **http://localhost:8001** in your browser.

## Architecture

Uses `ServiceContext` via FastAPI `lifespan` — the same infrastructure as `SilvaService`,
adapted for an HTTP server whose event loop is owned by Uvicorn.

See [`docs/services/web_interface.md`](../../docs/services/web_interface.md) for the full UI spec.
