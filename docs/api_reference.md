# API Reference

> **Status:** Planned for v0.8.0

## Web-Interface Management API

The **Web-Interface** (FastAPI + Swagger) will expose the management API for administrators:

- Device and profile CRUD
- Service configuration (desired state changes → DB → Controller reconciles via nudge)
- Real-time status dashboard (Read+Subscribe via Redis)

> [!NOTE]
> The Controller has **no HTTP API** beyond `/healthy`. Control actions flow through DB writes + `PUBLISH silvasonic:nudge "reconcile"` (State Reconciliation Pattern). See [ADR-0017](adr/0017-service-state-management.md) and [controller.md](services/controller.md).
