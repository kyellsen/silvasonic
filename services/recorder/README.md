# silvasonic-recorder

> **Tier:** 2 (Application, Managed by Controller) · **Port:** 9500

The Recorder is the most critical service in the Silvasonic stack. It captures audio data from USB microphones and writes it to local NVMe storage. Multiple Recorder instances may run concurrently, each managed by the Controller.

> **Implementation Status:** Scaffold (v0.1.0). Health monitoring is implemented. Audio capture is planned for v0.4.0.

---

## Immutability Rules

The Recorder is an **immutable Tier 2** service. This means:

- **No database access.** The Recorder has no connection to TimescaleDB or any other database. This is strictly forbidden (ADR-0013).
- **Profile Injection.** All configuration is provided via environment variables set by the Controller at container creation time.
- **No self-modification.** The Recorder does not change its own state or configuration at runtime.
- **Stateless container.** The only persistent artifact is the audio data written to the bind-mounted workspace volume.

---

## Health Endpoint

The Recorder exposes a health endpoint at `GET /healthy` on port `9500` (internal). This is used by the Compose healthcheck and the Controller to monitor Recorder status.

---

## Lifecycle

- **Not auto-started.** The Recorder uses the `managed` Compose profile and does not start with `just start`.
- **Started by Controller.** The Controller spawns Recorder instances as needed, injecting the appropriate profile (device, sample rate, channel config).
- **Graceful shutdown.** The Recorder handles `SIGTERM` and `SIGINT` for clean shutdown.

---

## Implementation Status

| Feature                  | Status                                         |
| ------------------------ | ---------------------------------------------- |
| Health server            | ✅ Implemented (`:9500/healthy`)                |
| Recording health monitor | ✅ Implemented (placeholder, hardcoded healthy) |
| Signal handling          | ✅ Implemented (graceful shutdown)              |
| Audio capture logic      | ⏳ Planned (v0.4.0)                             |

---

## References

- [ADR-0013: Tier 2 Container Management](../../docs/adr/0013-tier2-container-management.md)
- [Port Allocation](../../docs/arch/port_allocation.md) — Recorder on port 9500
