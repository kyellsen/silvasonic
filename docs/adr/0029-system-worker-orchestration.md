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

To keep the `SystemWorkerEvaluator` universally extensible (KISS) and Configuration-Driven, we establish the following **Singleton-Worker State Convention**:
- Each singleton worker (e.g. `birdnet`, `batdetect`) possesses an isolated, dedicated Pydantic configuration namespace within the `system_config` JSONB table.
- This namespace must hold both its runtime business logic (e.g., `confidence_threshold`) AND its orchestration toggle (`enabled: bool`).
- The generic `SystemWorkerEvaluator` purely matches this `enabled` property to execute the container lifecycle, enforcing a single source of truth and deprecating legacy relational toggle tables (e.g. `system_services`).

To configure the container specs, we introduce a static Python-based **Worker Registry** (`worker_registry.py`). This registry will hold plain dataclasses defining the operational footprint (`config_key`, `container_name`, `oom_score_adj`, `mem_limit`) for each supported background worker. 

The Controller's `ReconciliationLoop` will execute both evaluators sequentially, safely aggregating their target specs by isolating them with individual `try...except` blocks before dispatching to Podman.

## Rationale
1. **Architecture Extensibility (Open-Closed Principle):** Adding `batdetect` later requires zero changes to the Controller's logic. A developer only needs to append a new `BackgroundWorker` definitions to the `SYSTEM_WORKERS` Python list.
2. **Crash Isolation:** If evaluating the `birdnet` database configuration yields a crash, catching it explicitly prevents the `recorder` specs from being lost. The `sync_state` engine still successfully keeps microphones recording.
3. **Data Integrity:** This strictly enforces the "Data Capture Integrity is paramount" directive by shielding the hardware capturing pipeline from backend AI worker failures.
4. **Type-Safety:** Using a static Python list in `worker_registry.py` provides full `mypy` type validation, preventing misspelled container flags without needing to parse or validate external JSON/YAML templates.

## Consequences
- **Positive:** Recorder orchestration is entirely shielded from analysis worker crashes.
- **Positive:** Trivial scalability for future singleton containers.
- **Positive:** Quality of Service Limits (oom_score_adj, mem_limit) for all background tasks are defined cleanly in one file.
- **Negative:** Requires introducing a minor structural refactor (adding the registry and evaluator classes) to the Controller rather than a quick 2-line hardcoded hack.

## References
- [ADR-0017: State Reconciliation Pattern](0017-state-reconciliation-pattern.md)
- [ADR-0018: Worker Pull Orchestration](0018-worker-pull-orchestration.md)
- [ADR-0020: Resource Limits & QoS](0020-resource-limits-qos.md)
- [Milestone v0.8.0 Phase 4](../development/milestones/milestone_0_8_0.md)
