# ADR-0031: Runtime Tuning via DB Snapshot Refresh

> **Status:** Accepted • **Date:** 2026-04-11

## 1. Context & Problem

Silvasonic's Tier 2 containers were originally designed as **strictly immutable** (ADR-0013): all configuration is injected at launch time, and any change requires a container restart via the Controller.

While this model is correct for **lifecycle orchestration** (starting, stopping, resource limits), it forces unnecessary restarts for **domain tuning parameters** — values like BirdNET's `min_confidence` or the Janitor's disk thresholds that are pure post-processing filters with no impact on container resources.

Users expect a responsive "Mischpult" (mixing console) experience: adjust a threshold in the Web-Interface, see the effect within seconds — without the Controller restarting a container and interrupting in-progress work.

## 2. Decision

**We chose:** A three-tier field classification with worker-owned DB polling at safe loop boundaries.

### 2.1. Field Classification

Every configuration field is classified into exactly one of three categories:

| Category | Behavior | Who Owns the Change | Examples |
| --- | --- | --- | --- |
| **Operational Immutable** | Requires container restart | Controller (via `modules`) | `thread_count`, model path, container mounts, QoS limits |
| **Domain Mutable (Snapshot)** | Reloaded at next loop boundary | Worker (self-polling) | `min_confidence`, `sensitivity`, `overlap_s`, `processing_order`, Janitor thresholds, `index_interval_s` |
| **Domain Mutable (Snapshot + Recompute)** | Reloaded + triggers derived state recalculation | Worker (self-polling) | `station.latitude`, `station.longitude` → species mask recompute |

### 2.2. The Snapshot Refresh Pattern

Workers poll their relevant `settings` rows at the **top of each outer-loop iteration**, before claiming the next work item:

1. `SELECT section, updated_at FROM settings WHERE section IN (...)` — lightweight index-only scan.
2. Compare `updated_at` against a local cache (`_config_updated_at`).
3. **If changed:** Call `load_config()` to re-parse the JSONB blob via Pydantic.
4. **If unchanged:** No-op. No log output, no Pydantic parsing, minimal overhead.

This ensures:
-  A work item is **never** processed with mixed settings (old start, new finish).
-  No push signals, no Redis messages, no runtime commands between Controller and Worker.
-  The Controller remains **ignorant** of domain parameter changes.

### 2.3. Infrastructure

The `SilvaService` base class provides:
- `_config_sections: list[str]` — declared by subclasses to specify which `settings` sections to monitor.
- `_config_updated_at: dict[str, datetime]` — staleness cache.
- `_refresh_config()` — the polling method, called by workers at loop boundaries.

Subclasses that do not declare `_config_sections` (e.g. Recorder, which has no DB access) incur zero overhead — `_refresh_config()` returns immediately.

### 2.4. Relationship to ADR-0013

ADR-0013's immutability doctrine is preserved in its entirety for **lifecycle orchestration**. This ADR adds a complementary layer for **domain tuning** that does not involve the Controller at all.

| Change Type | Table | Who Reacts | Controller Involved? |
| --- | --- | --- | --- |
| Lifecycle toggle (`enabled`) | `modules` | Controller → start/stop container | Yes (Redis nudge) |
| Domain tuning (thresholds, sensitivity) | `settings` | Worker → self-polling at loop boundary | No |
| Operational config (thread_count, model) | `settings` | Requires restart via Controller | Yes |

### 2.5. Field Classification Matrix

#### BirdNET (`settings` sections: `birdnet`, `station`)

| Field | Category | Notes |
| --- | --- | --- |
| `min_confidence` | Snapshot | Post-processing float comparison |
| `sensitivity` | Snapshot | Sigmoid parameter |
| `overlap_s` | Snapshot | Frame slide rate |
| `processing_order` | Snapshot | SQL `ORDER BY` direction |
| `station.latitude` | Snapshot + Recompute | Triggers `_get_allowed_species_mask()` |
| `station.longitude` | Snapshot + Recompute | Triggers `_get_allowed_species_mask()` |
| `thread_count` | Operational Immutable | TFLite Interpreter C++ allocation |

#### Processor (`settings` section: `storage`)

| Field | Category | Notes |
| --- | --- | --- |
| `warning_percent` | Snapshot | Float comparison in `evaluate_mode()` |
| `critical_percent` | Snapshot | Float comparison |
| `emergency_percent` | Snapshot | Float comparison |
| `cleanup_batch_files` | Snapshot | SQL `LIMIT` clause |
| `cleanup_interval_s` | Snapshot | Sleep timing + `_janitor_every_n` recompute |
| `index_interval_s` | Snapshot | Sleep duration |

#### UploadWorker (`settings` sections: `sync`, `station`)

All fields are Snapshot. The UploadWorker already implements this pattern natively via `_fetch_config()` per loop iteration (predates this ADR).

## 3. Options Considered

* **Push-based reload via Redis Pub/Sub:** Rejected. Adds coupling between Controller/API and workers. Violates KISS. Workers already have a natural polling cadence.
* **SIGHUP signal for config reload:** Rejected. Requires signal plumbing through Podman. Not portable. No granularity (reloads everything).
* **Separate `config_refresh.py` utility:** Rejected. The existing `load_config()` hook in `SilvaService` already provides the mechanism. A new module would be over-engineering.
* **Reload `load_config()` every iteration without staleness check:** Rejected. Causes log spam (Processor logs all fields on each `load_config()` call) and ~43,000 unnecessary DB queries per day.

## 4. Consequences

* **Positive:**
    * "Mischpult" UX — threshold changes take effect within seconds, not minutes.
    * No container restarts for domain tuning — no interrupted work items.
    * Clean separation: Controller owns lifecycle, Workers own domain tuning.
    * Zero overhead when config hasn't changed (index-only `updated_at` check).
    * Pattern already proven by UploadWorker — formalized, not invented.
* **Negative:**
    * Workers must declare `_config_sections` — one line per subclass.
    * `SettingsSection.updated_at` requires `onupdate=` — silent timestamp drift if forgotten.
    * Debugging requires awareness that config can change between loop iterations.
    * Operational Immutable fields (e.g. `thread_count`) update in `self.birdnet_config` but have no runtime effect until restart — potentially confusing without documentation.
