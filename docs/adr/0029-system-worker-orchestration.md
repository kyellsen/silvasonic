# ADR-0029: System Worker Orchestration

## Status
Accepted

## Context
As the Silvasonic system expands with Tier 2 analysis containers (e.g., BirdNET, BatDetect, Weather), the Controller must orchestrate their lifecycle (starting and stopping). Originally, container orchestration was tightly coupled to hardware devices (`DeviceStateEvaluator`), which yields a `Tier2ServiceSpec` for each enrolled microphone. 

Unlike Recorders which map 1:1 to USB microphones, background analysis workers are singletons. They run exactly once per node and pull data asynchronously from the database (Worker Pull pattern, ADR-0018).
If we hardcode singleton workers into the existing hardware evaluation loop, we violate the Single Responsibility Principle and risk a configuration error in a background worker crashing the evaluation loop, thereby halting audio recordings (Primary Directive: Data Capture Integrity).

## Decision
We will decouple Tier 2 orchestration into separate **State Evaluators**:
1. **`DeviceStateEvaluator`**: Dedicated exclusively to mapping hardware devices to Recorder containers.
2. **`SystemWorkerEvaluator`**: A new, generic evaluator that manages singleton system workers.

### Separation of Concerns: Orchestration vs. Configuration

Lifecycle orchestration (start/stop) and domain configuration (thresholds, intervals) are **strictly separated**:

- **`managed_services` table (DB):** A dedicated relational table holds the orchestration toggle (`enabled: bool`) for each Tier-2 singleton. The `SystemWorkerEvaluator` queries this table with a simple `SELECT name FROM managed_services WHERE enabled = true`. This keeps the Controller's orchestration logic free from parsing complex JSONB payloads.
- **`system_config` table (DB):** Holds purely domain/business settings (e.g., `confidence_threshold`, `overlap`, `sensitivity`) as Pydantic-validated JSONB blobs. Workers dynamically poll these settings at safe loop boundaries via DB Snapshot Refresh (ADR-0031), allowing runtime tuning without container restarts.

> **Why not JSONB?** Mixing lifecycle toggles into `system_config` JSONB violates Separation of Concerns, creates Read-Modify-Write race conditions for concurrent UI updates, and forces the Controller to parse foreign domain payloads just to find a boolean flag.

### Worker Registry

To configure the container specs, we introduce a static Python-based **Worker Registry** (`worker_registry.py`). This registry holds plain dataclasses defining the operational footprint (`container_name`, `oom_score_adj`, `mem_limit`) for each supported background worker.

The Controller's `ReconciliationLoop` executes both evaluators sequentially, safely aggregating their target specs by isolating them with individual `try...except` blocks before dispatching to Podman.

## Rationale
1. **Architecture Extensibility (Open-Closed Principle):** Adding `batdetect` later requires zero changes to the Controller's logic. A developer only needs to append a new `BackgroundWorker` definition to the `SYSTEM_WORKERS` Python list and insert a row into `managed_services`.
2. **Crash Isolation:** If evaluating the `birdnet` database configuration yields a crash, catching it explicitly prevents the `recorder` specs from being lost. The `sync_state` engine still successfully keeps microphones recording.
3. **Data Integrity:** This strictly enforces the "Data Capture Integrity is paramount" directive by shielding the hardware capturing pipeline from backend AI worker failures.
4. **Type-Safety:** Using a static Python list in `worker_registry.py` provides full `mypy` type validation, preventing misspelled container flags without needing to parse or validate external JSON/YAML templates.
5. **Atomic Toggles:** A simple `UPDATE managed_services SET enabled = false WHERE name = 'birdnet'` is atomic — no JSONB Read-Modify-Write cycle, no race conditions from concurrent Web-UI users.

## Consequences
- **Positive:** Recorder orchestration is entirely shielded from analysis worker crashes.
- **Positive:** Trivial scalability for future singleton containers.
- **Positive:** Quality of Service Limits (oom_score_adj, mem_limit) for all background tasks are defined cleanly in one file.
- **Positive:** Clean separation — Controller never parses domain-specific JSONB to determine container lifecycle.
- **Negative:** Requires introducing a minor structural refactor (adding the registry, evaluator, and `managed_services` table) to the Controller rather than a quick 2-line hardcoded hack.

## References
- [ADR-0017: Service State Management](0017-service-state-management.md)
- [ADR-0018: Worker Pull Orchestration](0018-worker-pull-orchestration.md)
- [ADR-0020: Resource Limits & QoS](0020-resource-limits-qos.md)
- [ADR-0023: Configuration Management](0023-configuration-management.md)
- [Milestone v0.8.0 Phase 4](../development/milestones/milestone_0_8_0.md)
