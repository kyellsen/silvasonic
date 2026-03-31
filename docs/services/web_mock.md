# Web-Mock Service

> **Status:** Implemented (since v0.2.0) · **Tier:** 1 · **Port:** 8001

Development UI shell for the Silvasonic Web Interface. Serves the complete UI
(FastAPI + Jinja2 + HTMX + Alpine.js + Tailwind CSS + DaisyUI) with mock data
for most views. Uses the **real database** for Settings persistence and **Redis**
for heartbeat publishing. Precursor to the production Web-Interface (v0.9.0).

→ Full documentation: [services/web-mock/README.md](https://github.com/kyellsen/silvasonic/blob/main/services/web-mock/README.md)
