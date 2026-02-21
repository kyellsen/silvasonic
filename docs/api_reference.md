# API Reference

> **Status:** Planned for v0.8.0

## Controller Operational API

The Controller will expose a small HTTP API on port `9100` for operational commands. See [Controller Service](services/controller.md) for the endpoint specification.

## Web-Interface Management API

The Web-Interface will expose a full REST API with Swagger/OpenAPI documentation for device management, profile configuration, and system administration.

See [ADR-0003](adr/0003-frontend-architecture.md) — FastAPI + Jinja2 + HTMX + Alpine.js.
