# ADR-0030: Database Runtime Resilience (Soft-Fail Loops)

> **Status:** Accepted • **Date:** 2026-04-06

## 1. Context & Problem
The Silvasonic workers (Controller, Processor, BirdNET) all run continuous background polling loops (`while not _shutdown_event.is_set():`) pulling jobs from the database. Historically, the documentation and service blueprint did not explicitly outline how a worker should behave when the PostgreSQL database restarts or is transiently unavailable (e.g., during backups or network burps). 
This lack of standard led to an architectural drift in BirdNET, which followed a "Let-It-Crash" philosophy, dying entirely on `InterfaceError` because its database connection was unshielded in the outer loop. While `SilvaService` ensures safe pod-level restarts (dying-gasp), a container crash causes massive performance penalties for ML workers by forcing them to dump and re-allocate gigabytes of tensor memory.

## 2. Decision
**We chose:** The "Soft-Fail" (Graceful Retry) pattern for cyclic transient I/O.

All continuous polling loops MUST wrap their operational cycle (e.g. database querying or persisting data) in an explicit `try/except` boundary. Instead of crashing the container, transient errors must:
1. Be caught and logged semantically (e.g. `logger.warning("worker.db_cycle_failed", exc_info=exc)`).
2. Report the degradation to the web dashboard via `self.health.update_status(..., False, "database_unavailable")`.
3. Sleep for a short, constant backoff (e.g. `_DB_RETRY_SLEEP_S = 5.0`).
4. `continue` the outer loop.

Startup constraints, malformed schemas, and fatal configuration initializations MUST continue to fail-fast.

**Reasoning:**
Soft-failing protects expensive ML inference models (like TFLite in BirdNET) from unnecessary tear-downs during momentary infrastructure disruptions. Furthermore, by keeping the process alive, the Web-Interface dashboard retains clear visibility over the specific failure reason ("database_unavailable") instead of defaulting to a generic "container dead/restarting" overlay.

## 3. Options Considered
* **Let-It-Crash Only**: Rejected because the time cost of reloading AI Edge LiteRT models outweighs the simplicity of container restarts.
* **Exponential Backoff Library (e.g. Tenacity)**: Rejected to preserve the KISS principle. The architecture values simple, explicit, fixed interval sleeps (5 seconds) over introducing complex generic retry mechanisms for basic worker orchestration.

## 4. Consequences
* **Positive:** ML Workers retain their in-memory models during brief disruptions. Improved transparency and logging in the UI during outages. High convergence between Controller, Processor, and BirdNET architectures.
* **Negative:** Developers must remember to add the outer `try/except` guard manually, which we mitigate by updating `service_blueprint.md`.
