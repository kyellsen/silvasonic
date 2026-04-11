# ADR-0030: Logging Cadence & Stats Extensibility

> **Status:** Accepted • **Date:** 2026-04-06

## 1. Context & Problem

Silvasonic's backend consists of a Controller and various Tier-2 or Background Workers (Recorder, UploadWorker, Indexer, BirdNET). These services operate continuously and process thousands of discrete events over time (audio files, log lines, uploads).

Currently, logging behavior is fragmented and prone to spam:
- `ControllerStats`, `RecordingStats` and `UploadStats` implemented a "Two-Phase" logging pattern (5 minutes of verbose startup logging followed by periodic 5-minute summaries). While effective in reducing log-spam (Loki/Promtail), this lead to duplicated boilerplate for time measurement (`time.monotonic()`) and edge-case transitions.
- Conversely, modules like the `Indexer`, `Janitor`, and `BirdNET` log indiscriminately *per action*, flooding the SIEM view and slowing down log rotation.

A forced abstract base class (`ABC`) to handle stats tracking across the board was considered but discarded due to the risk of "False Abstraction". The tracker instances operate under vastly different concurrency assumptions (multi-threaded GIL locks in `RecordingStats`, asynchronous loop snapshots in `ControllerStats`, lock-free async runs in `UploadStats`).

## 2. Decision

We mandate a unified **Two-Phase Logging Pattern** ("Logging Contract") via **Composition** instead of inheritance, to eliminate log spam while acknowledging the diverse concurrency models. This contract becomes an integral extension of the `SilvaService` blueprint.

### 2.1. Composition with `TwoPhaseWindow`
We introduce `packages/core/src/silvasonic/core/logging/two_phase.py` (`TwoPhaseWindow`).
This helper strictly encapsulates the math of time comparisons (`time.monotonic()`) and phase transitions (evaluating whether a system is in startup phase or steady state). It performs no logging, maintains no thread-locks, and has no domain-metrics counters. Services instantiate it to safely trigger their domain-specific logs under their required concurrency model.

### 2.2. The Structured Logging Contract
When logging summary metrics in structured format (`structlog`), services MUST adhere to the following event names to allow uniform Promtail/Loki dashboarding:
- `<service/module>.startup_phase_complete`: Logs exactly once when transitioning to steady state.
- `<service/module>.summary`: Emitted periodically during steady state.
- `<service/module>.final_summary`: Emitted when the service gracefully shuts down.

Additionally, every summary JSON payload MUST include at the top level:
- `uptime_s`: (float) Precision time since instantiation.
- `interval_s`: (float) Precision time since the last summary.

### 2.3. Configuration Tier
Following **ADR-0023**, the intervals for logging cadence are considered **Operational Infrastructure** state, not Business Domain state.
- Fallback defaults (`DEFAULT_LOG_STARTUP_S`, `DEFAULT_LOG_SUMMARY_INTERVAL_S`) reside in `packages/core/src/silvasonic/core/logging/constants.py`.
- Service-specific configuration continues to use Environment overrides (`.env` -> `BaseSettings`, e.g., `SILVASONIC_PROCESSOR_LOG_STARTUP_S`).
- There is no central database configuration table for logging rhythms.

## 3. Options Considered

- **Abstract Base Class (`TwoPhaseTracker`)**: Rejected. Would force identical thread-locking paradigms onto all services, creating overhead for lock-free services and preventing `async` snapshot injection for services like the Controller.
- **`system_config` Database Table**: Rejected. Dynamically changeable JSON intervals for system logging violate the immutable-container directive and overcomplicate the database settings tier. Overrides belong in `.env`.
- **Ignore spammy services:** Rejected. Technical debt in the logging sphere causes real-world pain for deployments over cellular/LTE connections.

## 4. Consequences

- **Positive:** Massive reduction in log spam for remote edge devices. Unified SIEM parsing via `interval_s` and `uptime_s` metadata. Clear decoupled API boundaries for future services (e.g. BatDetect, Weather worker) without locking constraints.
- **Negative:** Existing services (BirdNET, Indexer) require immediate refactoring to align with this standard, shifting their logs from per-action prints to bundled counters.
