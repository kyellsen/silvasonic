# Lifecycle & Configuration Architecture

> **Status:** Normative (Mandatory) · **Scope:** System-wide configuration and service lifecycle management
> **Implements:** [ADR-0013](../adr/0013-tier2-container-management.md), [ADR-0023](../adr/0023-configuration-management.md), [ADR-0029](../adr/0029-system-worker-orchestration.md), [ADR-0031](../adr/0031-runtime-tuning-snapshot-refresh.md)

This document describes **how Silvasonic services are configured** and **when they react to configuration changes**. It synthesises the individual ADRs into a single, coherent reference.

For **how services communicate with each other** (Redis, heartbeats, nudge), see [Messaging Patterns](messaging_patterns.md).

---

## 1. Configuration Tiers

Configuration lives in exactly three places, each serving a distinct purpose:

| Tier | Storage | Set By | Examples | Runtime Changeable? |
| --- | --- | --- | --- | --- |
| **Infrastructure** | `.env` file | Admin (SSH / Ansible) | `SILVASONIC_WORKSPACE_PATH`, `SILVASONIC_DB_HOST`, `SILVASONIC_PODMAN_SOCKET` | No — requires container rebuild |
| **Application Settings** | `system_config` table (JSONB) | YAML Seed → Web-Interface | `latitude`, `confidence_threshold`, `janitor_threshold_warning` | Yes — see §3 below |
| **Authentication** | `users` table | YAML Seed → Web-Interface | `username`, `password_hash` | Yes — Frontend settings page |

> **Full details:** [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)

---

## 2. Two Tables, Two Purposes

### `system_config` — **WHAT** a service should do (domain parameters)

Key-value store with JSONB blobs, validated by Pydantic schemas:

| Key | Pydantic Schema | Used By |
| --- | --- | --- |
| `system` | `SystemSettings` | All services (latitude, longitude, station name) |
| `processor` | `ProcessorSettings` | Processor (Janitor thresholds, Indexer intervals) |
| `cloud_sync` | `CloudSyncSettings` | UploadWorker (enabled flag, polling, bandwidth) |
| `birdnet` | `BirdnetSettings` | BirdNET (confidence, sensitivity, overlap) |

### `managed_services` — **WHETHER** a service should run (lifecycle on/off)

| Column | Type | Purpose |
| --- | --- | --- |
| `name` | TEXT PK | Service identifier (e.g. `"birdnet"`) |
| `enabled` | BOOL | Lifecycle toggle |
| `updated_at` | TIMESTAMPTZ | Change detection |

### The Rule

| Question | Table | Who reacts |
| --- | --- | --- |
| "Should this container **exist**?" | `managed_services` | **Controller** (starts/stops via Podman) |
| "**How** should this container work?" | `system_config` | **The service itself** (reads at next loop boundary) |

> **Full details:** [ADR-0029: System Worker Orchestration](../adr/0029-system-worker-orchestration.md)

---

## 3. Field Classification: Immutable vs. Mutable

Every configuration field is classified into exactly one of three categories:

| Category | Behaviour | Who Owns the Change | Examples |
| --- | --- | --- | --- |
| **Operational Immutable** | Requires container restart | Controller (via `managed_services`) | `threads`, model path, container mounts, QoS limits |
| **Domain Mutable (Snapshot)** | Reloaded at next loop boundary | Worker (self-polling via `_refresh_config()`) | `confidence_threshold`, `sensitivity`, Janitor thresholds, `indexer_poll_interval` |
| **Domain Mutable (Snapshot + Recompute)** | Reloaded + triggers derived state recalculation | Worker (self-polling) | `system.latitude`, `system.longitude` → species mask recompute |

### BirdNET Field Matrix (`system_config` keys: `birdnet`, `system`)

| Field | Category | Notes |
| --- | --- | --- |
| `confidence_threshold` | Snapshot | Post-processing float comparison |
| `sensitivity` | Snapshot | Sigmoid parameter |
| `overlap` | Snapshot | Frame slide rate |
| `processing_order` | Snapshot | SQL `ORDER BY` direction |
| `system.latitude` | Snapshot + Recompute | Triggers `_get_allowed_species_mask()` |
| `system.longitude` | Snapshot + Recompute | Triggers `_get_allowed_species_mask()` |
| `threads` | Operational Immutable | TFLite Interpreter C++ allocation |

### Processor Field Matrix (`system_config` key: `processor`)

| Field | Category | Notes |
| --- | --- | --- |
| `janitor_threshold_warning` | Snapshot | Float comparison in `evaluate_mode()` |
| `janitor_threshold_critical` | Snapshot | Float comparison |
| `janitor_threshold_emergency` | Snapshot | Float comparison |
| `janitor_batch_size` | Snapshot | SQL `LIMIT` clause |
| `janitor_interval_seconds` | Snapshot | Sleep timing + `_janitor_every_n` recompute |
| `indexer_poll_interval` | Snapshot | Sleep duration |

### UploadWorker (`system_config` keys: `cloud_sync`, `system`)

All fields are Snapshot. The UploadWorker implements this pattern natively via `_fetch_config()` per loop iteration.

> **Full details:** [ADR-0031: Runtime Tuning via DB Snapshot Refresh](../adr/0031-runtime-tuning-snapshot-refresh.md)

---

## 4. The Snapshot Refresh Pattern

Workers poll their relevant `system_config` rows at the **top of each outer-loop iteration**, before claiming the next work item:

```
┌─────────────────────────────────────────────────────────────┐
│  Worker Loop (BirdNET / Processor)                           │
│                                                             │
│  1. _refresh_config()                                        │
│     └─ SELECT key, updated_at WHERE key IN (...)             │
│     └─ Compare with cached timestamps                        │
│     └─ If changed: load_config() → update self.settings      │
│                                                             │
│  2. [Optional] Recompute derived state                       │
│     └─ BirdNET: species mask if lat/lon changed              │
│     └─ Processor: _janitor_every_n ratio                     │
│                                                             │
│  3. Claim work item (SELECT FOR UPDATE SKIP LOCKED)          │
│                                                             │
│  4. Process with consistent, fresh settings                  │
│     └─ A work item is NEVER processed with mixed settings    │
└─────────────────────────────────────────────────────────────┘
```

**Key invariant:** Config refresh happens *before* work is claimed. A recording is never analysed with settings that changed mid-processing.

**Infrastructure:** The `SilvaService` base class provides:
- `_config_keys: list[str]` — declared by subclasses (e.g. `["birdnet", "system"]`)
- `_config_updated_at: dict[str, datetime]` — staleness cache
- `_refresh_config()` — the polling method with staleness check

Services without `_config_keys` (e.g. Recorder) incur zero overhead.

---

## 5. Control Flow: Who Reacts to What?

```
┌──────────────────────────────────────────────────────────┐
│  LIFECYCLE CHANGE (managed_services.enabled)              │
│                                                          │
│  Web-Interface ──[DB write]──► managed_services           │
│  Web-Interface ──[PUBLISH nudge]──► Redis                  │
│  Controller ──[reads DB, reconciles]──► Podman start/stop │
│                                                          │
│  Controller IS involved. Worker IS restarted.             │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  DOMAIN TUNING (system_config thresholds/sensitivity)     │
│                                                          │
│  Web-Interface ──[DB write]──► system_config              │
│  Worker ──[polls updated_at at loop boundary]──► self     │
│                                                          │
│  Controller is NOT involved. Worker is NOT restarted.     │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  OPERATIONAL CHANGE (threads, model path)                 │
│                                                          │
│  Admin ──[DB write]──► system_config                      │
│  Controller ──[nudge + restart]──► Podman stop + start    │
│                                                          │
│  Controller IS involved. Worker IS restarted.             │
└──────────────────────────────────────────────────────────┘
```

---

## 6. Service-Specific Behaviour

| Service | DB Access | Config Source | Refresh Strategy |
| --- | --- | --- | --- |
| **Controller** | Yes | `.env` (`ControllerSettings`) | No refresh — pure infrastructure settings |
| **Recorder** | **No** (AGENTS.md §1) | Environment (Profile Injection) | Fully immutable — restart required |
| **Processor** | Yes | `system_config` key `"processor"` | Snapshot Refresh per loop iteration |
| **BirdNET** | Yes | `system_config` keys `"birdnet"`, `"system"` | Snapshot Refresh + Lat/Lon species mask recompute |
| **UploadWorker** | Yes | `system_config` keys `"cloud_sync"`, `"system"` | Native per-iteration `_fetch_config()` |
| **Web-Mock** | Yes | `system_config` key `"system_settings"` | Per HTTP request (FastAPI Dependency) |

---

## See Also

*   [ADR-0013: Tier 2 Container Management](../adr/0013-tier2-container-management.md) — Container immutability doctrine
*   [ADR-0017: Service State Management](../adr/0017-service-state-management.md) — Desired vs. Actual state split
*   [ADR-0023: Configuration Management](../adr/0023-configuration-management.md) — Config tiers, YAML seed, Pydantic schemas
*   [ADR-0029: System Worker Orchestration](../adr/0029-system-worker-orchestration.md) — `managed_services` vs. `system_config`
*   [ADR-0031: Runtime Tuning via DB Snapshot Refresh](../adr/0031-runtime-tuning-snapshot-refresh.md) — Field classification and Snapshot Refresh pattern
*   [Messaging Patterns](messaging_patterns.md) — Redis heartbeats, nudge, Pub/Sub
