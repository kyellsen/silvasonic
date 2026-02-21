# Controller Service

> The central orchestration service — detects USB microphones, manages the device inventory, dynamically starts/stops Tier 2 containers via the Podman REST API, and exposes an operational API for immediate control commands.

## Operational API (v0.8.0)

The Controller exposes a small operational API on port `9100` for the Web-Interface to issue immediate actions:

| Endpoint                     | Method | Purpose                                           |
| ---------------------------- | ------ | ------------------------------------------------- |
| `/healthy`                   | GET    | Health check (existing — see Service Blueprint)   |
| `/api/v1/services`           | GET    | List all managed Tier 2 services and their status |
| `/api/v1/stop/<instance_id>` | POST   | Immediately stop a Tier 2 container               |
| `/api/v1/reconcile`          | POST   | Trigger immediate reconciliation cycle            |

> [!NOTE]
> This is **not** a full management REST API. CRUD operations on Devices, Profiles, and configuration are handled by the Web-Interface's own FastAPI backend. The Controller API is limited to operational commands that require Podman socket access.

## Control Flow

*   **Config changes** (enable/disable service, change profile): Web-Interface writes to DB → Controller reconciles on next loop (~30s).
*   **Immediate actions** (emergency stop, force reconcile): Web-Interface calls Controller API → Controller acts via `podman-py`.

See [ADR-0017](../adr/0017-service-state-management.md) and [Messaging Patterns](../arch/messaging_patterns.md) for details.

## Full Documentation

Die vollständige Dokumentation befindet sich im Service-Verzeichnis:

- **[Controller README](../../services/controller/README.md)** — Primary specification
