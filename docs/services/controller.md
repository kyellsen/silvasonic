# Controller Service

> **Tier:** 1 (Infrastructure) · **Port:** 9100 · **Status:** Scaffold

The Controller is the central orchestration service. It detects USB microphones, manages the device inventory, and dynamically starts/stops Tier 2 containers (Recorder, Uploader, etc.) via the Podman REST API.

For the full specification — including device state evaluation, enrollment state machine, reconciliation loop, and shutdown semantics — see:

- **[Controller README](../../services/controller/README.md)** — Primary specification

## API

The Controller itself does **not** expose a REST API for external consumers. Device and profile management endpoints will be provided by the **Web-Interface** service (FastAPI + Swagger) in a future version (see [ADR-0003](../adr/0003-frontend-architecture.md), [VISION.md](../../VISION.md) v0.6.0).

The Controller exposes only a health endpoint on port `9100` (`/healthy`).

## Configuration

| Variable                     | Description                               | Default                   |
| ---------------------------- | ----------------------------------------- | ------------------------- |
| `SILVASONIC_CONTROLLER_PORT` | Health endpoint port                      | `9100`                    |
| `CONTAINER_SOCKET`           | Path to Podman socket inside container    | `/var/run/container.sock` |
| `SILVASONIC_NETWORK`         | Podman network name for Tier 2 containers | `silvasonic-net`          |

## References

- [Controller README](../../services/controller/README.md) — Full specification
- [ADR-0013: Tier 2 Container Management](../adr/0013-tier2-container-management.md)
- [ADR-0016: Hybrid YAML/DB Profiles](../adr/0016-hybrid-yaml-db-profiles.md)
- [Port Allocation](../arch/port_allocation.md)
