# Controller Service

> The central orchestration service — detects USB microphones, manages the device inventory, and dynamically starts/stops Tier 2 containers via the Podman REST API. Follows the State Reconciliation Pattern (DB desired state + Redis nudge).

## Control Flow — State Reconciliation Pattern

The Controller has **no HTTP API** beyond the `/healthy` health endpoint. Control is exclusively declarative:

1. **Web-Interface** writes desired state to the database (e.g., `enabled=false` in `system_services`).
2. **Web-Interface** sends `PUBLISH silvasonic:nudge "reconcile"` — a simple wake-up signal.
3. **Controller** wakes up, reads DB, compares desired vs. actual state, acts via `podman-py`.

```
Web-Interface ──[DB Write]──► Database (desired state)
Web-Interface ──[PUBLISH]──► silvasonic:nudge ──► Controller
Controller ──[reconcile()]──► Podman ──► start/stop containers
```

> [!NOTE]
> If the nudge is lost (Controller restarting), the 30s reconciliation timer catches up automatically. The DB desired state is never lost — this makes the pattern robust against Controller restarts.

## Full Documentation

Die vollständige Dokumentation befindet sich im Service-Verzeichnis:

- **[Controller README](../../services/controller/README.md)** — Primary specification
