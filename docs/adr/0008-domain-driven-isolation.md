# ADR-0008: Domain-Driven Workspace Isolation

> **Status:** Accepted • **Date:** 2026-01-31


## 1. Context & Problem
> **NOTE:** References to `processor`, `uploader`, or `janitor` refer to future services (planned for v0.3.0+). Currently, only `recorder` and `controller` exist.
In a microservice architecture sharing a file system, there is a risk of a "Spaghetti" data layout where multiple services read/write to common directories. This leads to race conditions, accidental data deletion ("Noisy Neighbor"), and unclear ownership responsibilities. We need a layout that enforces ownership and structure.

## 2. Decision
**We chose:** A strict Domain-Driven folder structure within the workspace.
Each service gets exactly one top-level directory matching its service name (e.g., `recorder/`, `processor/`, `database/`). Services are prohibited from using generic shared folders (like `shared/` or `tmp/`) for persistent state.

**Reasoning:**
This enforces the "Single Writer" principle at the infrastructure level. If a directory is named `recorder`, it implies that *only* the Recorder service manages its lifecycle. It prevents collisions (e.g., two services trying to write `log.txt` to root) and makes debugging easier, as the location of an error log is predictable.

## 3. Options Considered
*   **Flat Hierarchy (Dump everything in root):**
    *   *Rejected because:* Unmaintainable chaose.
*   **Functional Hierarchy (`logs/`, `data/`):**
    *   *Rejected because:* Splits a service's context across multiple locations. We prefer keeping all reliable data for "Recorder" in one place.

## 4. Consequences
*   **Positive:**
    *   Clear ownership and accountability.
    *   Easy to wipe specific service data without affecting others.
    *   Prevents filename collisions.
*   **Negative:**
    *   Requires services to be configured with specific output paths (cannot just dump to CWD).
