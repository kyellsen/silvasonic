# Processor Service

> **Status:** implemented (v0.5.0)
>
> **Tier:** 1 (Infrastructure) · **Port:** 9200

Background workhorse for data ingestion, metadata indexing, and storage retention management.
Immutable Container pattern (ADR-0019): reads config from `system_config` on startup, restart to reconfigure.

**Full specification:** [Processor Service Spec](../../docs/services/processor.md)

## Features

### Indexer (`indexer.py`)

- Periodic filesystem polling of `recorder/*/data/processed/*.wav`
- Extracts WAV metadata via `soundfile`: duration, sample_rate, channels, file size
- Registers recordings in the `recordings` table (idempotent, no duplicates)
- Resolves matching raw file path for each processed segment
- Configurable poll interval (`ProcessorSettings.indexer_poll_interval`, default: 2s)

### Janitor (`janitor.py`)

- Monitors NVMe disk usage via `shutil.disk_usage()`
- Enforces escalating retention policy (ADR-0011 §6):

  | Mode             | Threshold | Criteria                                          |
  | ---------------- | --------- | ------------------------------------------------- |
  | **Housekeeping** | > 70%     | `uploaded=true` AND analysis complete              |
  | **Defensive**    | > 80%     | `uploaded=true` (regardless of analysis)           |
  | **Panic**        | > 90%     | Oldest files regardless of status                  |

- Soft Delete pattern: physical delete + DB row `local_deleted = true`
- Panic Mode fallback: filesystem `mtime`-based blind cleanup when DB is unreachable
- Uploader-Fallback: skips `uploaded` condition when no Uploader is configured
- Configurable thresholds, interval, and batch size via `ProcessorSettings`

### Reconciliation (`reconciliation.py`)

- Runs once on startup before the Indexer polling loop begins
- Heals Split-Brain state caused by Panic Mode blind deletion during DB outages
- Marks orphaned `recordings` rows (`local_deleted = false` but file missing) as `local_deleted = true`

### Service Lifecycle (`__main__.py`)

- `ProcessorService(SilvaService)` with health, heartbeat, graceful shutdown
- Runtime config loading from `system_config` table (`ProcessorSettings`)
- Reports indexer and janitor metrics in heartbeat payload
- Compose integration as Tier 1 service (depends on DB + Redis + Controller)

## Configuration

Runtime settings are stored in the `system_config` table (key: `processor`) and
seeded from `config/defaults.yml` by the Controller on startup (ADR-0023).

| Setting                        | Default | Description                           |
| ------------------------------ | ------- | ------------------------------------- |
| `janitor_threshold_warning`    | 70.0    | Disk % to trigger Housekeeping mode   |
| `janitor_threshold_critical`   | 80.0    | Disk % to trigger Defensive mode      |
| `janitor_threshold_emergency`  | 90.0    | Disk % to trigger Panic mode          |
| `janitor_interval_seconds`     | 60      | Seconds between Janitor cycles        |
| `janitor_batch_size`           | 50      | Max files deleted per cycle           |
| `indexer_poll_interval`        | 2.0     | Seconds between Indexer scans         |

Settings are editable at runtime via the Web-UI (v0.8.0). Changes require a
Processor restart to take effect (Immutable Container pattern).

## Modules

| Module               | Lines | Purpose                                  |
| -------------------- | ----- | ---------------------------------------- |
| `__main__.py`        | 82    | Service entry point, lifecycle, config   |
| `indexer.py`         | 71    | Filesystem polling, WAV registration     |
| `janitor.py`         | 122   | Disk monitoring, retention enforcement   |
| `reconciliation.py`  | 20    | Split-Brain healing on startup           |
| `settings.py`        | 8     | Environment variable bindings            |

## Tests

- **Unit:** 100% coverage on indexer, reconciliation, settings; 89% on janitor
- **Integration:** Testcontainer-based tests for indexer, janitor, reconciliation, lifecycle
- **System:** Full Podman lifecycle tests including resilience scenarios
- **Smoke:** Health endpoint and heartbeat validation

## See Also

- [Processor Service Spec](../../docs/services/processor.md) — Full design specification
- [ADR-0009](../../docs/adr/0009-zero-trust-data-sharing.md) — Zero-Trust Data Sharing
- [ADR-0011](../../docs/adr/0011-audio-recording-strategy.md) — Audio Recording Strategy (§6 Retention)
- [ADR-0019](../../docs/adr/0019-unified-service-infrastructure.md) — Unified Service Infrastructure
- [ADR-0023](../../docs/adr/0023-configuration-management.md) — Configuration Management
- [Milestone v0.5.0](../../docs/development/milestone_0_5_0.md) — Implementation plan
