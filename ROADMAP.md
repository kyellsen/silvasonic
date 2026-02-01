# Silvasonic Implementation Roadmap

This roadmap tracks the implementation status of all services, organized by Architectural Tiers (as defined in `README.md`) and Dataflow dependency.

**Legend:**
- 🔴 **Missing**: Service placeholder exists but is empty or missing content.
- 🟠 **Template**: Scaffolding exists (folder structure, config), but core logic offers only a template/skeleton.
- 🟡 **Partially Implemented**: Core features exist but are incomplete.
- 🟢 **Fully Implemented**: Feature-complete according to specification.
- ✅ **Verified**: Fully implemented (or stable partials) and verified by automated tests.

---

## 0. Shared Core
Foundation library used by all services.

| Service | Status | Test Coverage | Description |
| :--- | :--- | :--- | :--- |
| **packages/core** | 🟡 ✅ | **High** (Integration) | Shared library. DB models & Migrations (TimescaleDB) and Redis client are implemented and **Verified** via integration tests. Shared business logic is missing. |

---

## 1. Tier 1: Infrastructure
Managed by Podman Compose. Provides the runtime environment and extensive system management.

| Service | Status | Test Coverage | Description |
| :--- | :--- | :--- | :--- |
| **services/database** | 🟢 ✅ | **High** (Indirect) | PostgreSQL + TimescaleDB (Docker). functionality verified via `core` integration tests. |
| **services/redis** | 🟢 ✅ | **High** (Indirect) | Redis Cache/Queue (Docker). Connectivity verified via `core` integration tests. |
| **services/gateway** | 🔴 | None | Caddy Reverse Proxy for HTTPS/Auth. |
| **services/controller** | 🟠 | None | Hardware/Container manager & orchestrator. |
| **services/monitor** | 🟠 | None | System Watchdog (CPU, Disk, Temp). |
| **services/web-interface** | 🟠 | None | Local management console (FastAPI + HTMX). |
| **services/tailscale** | 🔴 | None | VPN mesh networking. |

---

## 2. Tier 2: Application
Managed by Controller. Implements the core bioacoustic pipeline (Dataflow logic).

| Service | Status | Test Coverage | Description |
| :--- | :--- | :--- | :--- |
| **services/recorder** | 🟠 | None | **[Input]** Captures audio. Buffers to RAM, writes dual-stream to NVMe. |
| **services/processor** | 🟠 | None | **[Process]** Indexes files, creates spectrograms, manages retention. |
| **services/batdetect** | 🟠 | None | **[Analyze]** On-device inference for bats. |
| **services/birdnet** | 🟠 | None | **[Analyze]** On-device inference for birds. |
| **services/weather** | 🟠 | None | **[Context]** Environmental sensor data collection. |
| **services/uploader** | 🟠 | None | **[Output]** Exfiltrates data to remote storage/API. |

---

## 3. Reference
| Service | Status | Test Coverage | Description |
| :--- | :--- | :--- | :--- |
| **services/template** | 🟠 ✅ | **Low** (Smoke) | Reference implementation/Scaffolding. Contains basic smoke tests. |
