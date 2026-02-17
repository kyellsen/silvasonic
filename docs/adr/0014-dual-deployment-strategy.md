# ADR-0014: Dual Deployment Strategy — Compose (Dev) / Quadlets (Prod)

**Date:** 2026-02-17
**Status:** Accepted (Implementation planned for v1.0.0)

## 1. Context

Silvasonic is designed to run autonomously for years on unattended edge devices (Raspberry Pi 5). The current development workflow uses `podman-compose` with `compose.yml` for Tier 1 service orchestration. While this works well for local development (`just start/stop/build`), `podman-compose` is a Python-based translation layer over Podman CLI commands — it is **not** a production-grade process manager.

For a system where "Data Capture Integrity is paramount" and autonomous operation is measured in years, the weakest link in the chain matters. `podman-compose` introduces:

*   A **single point of failure** — if the compose process crashes, service restart management is lost.
*   No native integration with the OS init system — service ordering, crash recovery, and boot dependencies rely on compose logic rather than the kernel's process manager.
*   An unnecessary abstraction layer between the OS and the containers.

## 2. Decision

**We chose:** A dual deployment strategy.

| Environment     | Tool                                                                    | Purpose                                               |
| --------------- | ----------------------------------------------------------------------- | ----------------------------------------------------- |
| **Development** | `podman-compose` + `compose.yml`                                        | Fast iteration, familiar DX (`just start/stop/build`) |
| **Production**  | **Podman Quadlets** (`.container`, `.volume`, `.network` systemd units) | Maximum resilience, native OS integration             |

### What are Quadlets?

Podman Quadlets (available since Podman 4.4, stable in 4.6+) allow defining containers as **native systemd services**. Instead of `compose.yml`, each Tier 1 service gets a `.container` unit file:

```ini
# /etc/containers/systemd/silvasonic-database.container
[Unit]
Description=Silvasonic TimescaleDB
After=network-online.target

[Container]
Image=localhost/silvasonic-database:latest
ContainerName=silvasonic-database
EnvironmentFile=/etc/silvasonic/.env
Volume=silvasonic-db-data:/var/lib/postgresql/data:Z
Network=silvasonic.network
PublishPort=5432:5432
HealthCmd=pg_isready -U silvasonic
HealthInterval=10s
HealthRetries=5
HealthStartPeriod=15s

[Service]
Restart=always
RestartSec=5s
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target default.target
```

Systemd then manages start ordering (`After=`), crash recovery (`Restart=always`), boot activation (`WantedBy=`), and clean shutdown — without any intermediary tool.

**Reasoning:**

*   **Resilience:** systemd is the battle-tested Linux process manager. It handles crash recovery, boot ordering, and watchdog timers natively. A container crashing at 3 AM in the forest is restarted within seconds — no compose process required.
*   **Zero Dependencies:** No Python runtime, no `podman-compose` installation. The OS manages containers directly.
*   **Boot Reliability:** `WantedBy=multi-user.target` guarantees all Tier 1 services start automatically after power loss — the single most critical requirement for autonomous field stations.
*   **Alignment with Podman-Only Strategy:** Quadlets are the Podman-native production deployment method (see ADR-0004, ADR-0013). Using them aligns with the project's commitment to Podman as the sole container engine.
*   **Development Unchanged:** `compose.yml` and `podman-compose` remain the developer-facing tools. The Quadlet files are generated/maintained by the Ansible provisioning playbooks.

## 3. Options Considered

*   **`podman-compose` in Production:** Status quo. Simple but fragile. No native crash recovery, no systemd integration. Rejected for production use.
*   **`podman generate systemd`:** Generates legacy systemd unit files from running containers. Works but is deprecated in favor of Quadlets. Rejected.
*   **Podman Quadlets:** Native systemd integration via `.container` unit files. Production-grade, zero dependencies, battle-tested. **Chosen.**
*   **Kubernetes/K3s:** Vastly overengineered for a single-node edge device. Rejected.

## 4. Consequences

*   **Positive:**
    *   Tier 1 services survive crashes and power losses with automatic, systemd-managed restarts.
    *   No runtime dependency on `podman-compose` in production.
    *   Clean separation between development tooling (compose) and production deployment (Quadlets).
    *   Ansible can template and deploy `.container` files as part of fleet provisioning.
    *   Aligns with "Resilience over Features" design principle.
*   **Negative:**
    *   Two parallel "descriptions" of Tier 1 services: `compose.yml` (dev) and `.container` files (prod). Must be kept in sync.
    *   Developers unfamiliar with systemd units have a learning curve.
    *   Quadlets require Podman ≥ 4.4 on the target device.

## 5. Implementation Notes

*   **Scope:** Tier 1 services only. Tier 2 services are managed by the Controller via `podman-py` (see ADR-0013).
*   **Timeline:** v1.0.0 (production-ready field deployment).
*   **Provisioning:** Quadlet files will be generated/deployed by the Ansible playbooks during device provisioning.
*   **Files:** `.container`, `.volume`, and `.network` unit files will reside in `deploy/quadlets/` within the repository and be installed to `/etc/containers/systemd/` on the target device.
*   **Compose Retained:** `compose.yml` remains the canonical development tool. No changes to the dev workflow.
