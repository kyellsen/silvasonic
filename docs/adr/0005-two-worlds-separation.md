# ADR-0005: Separation of Immutable Code & Mutable State ("Two-Worlds")

> **Status:** Accepted • **Date:** 2026-01-31

## 1. Context & Problem
In an embedded/edge environment like Silvasonic, mixing application code with runtime data creates significant operational risks. If artifacts (logs, recordings, database files) are stored within the application directory, "resetting" the application to a clean state becomes impossible without losing data. Conversely, updating the application code (git pull) becomes risky if user data is interspersed with source files. We need a strategy to decouple the lifecycle of the software from the lifecycle of the data.

## 2. Decision
**We chose:** The "Two-Worlds" architecture principle.
*   **World A (Immutable):** Code resides in `SILVASONIC_REPO_PATH` (e.g., `/mnt/data/dev/apps/silvasonic`). Containers have read-only access here (except in explicit dev-mode).
*   **World B (Mutable):** State resides in `SILVASONIC_WORKSPACE_PATH` (e.g., `/mnt/data/dev_workspaces/silvasonic`). This is the ONLY location where writing is permitted.

**Reasoning:**
This strict separation treats the application code as "firmware"—immutable and easily replaceable. The state is treated as "user data"—precious and mutable. It allows us to perform a "Factory Reset" simply by deleting the workspace directory, while the code remains untouched. It also simplifies backups (backup only the workspace) and updates (git pull the repo without fear of conflict).

## 3. Options Considered
*   **Mixed Directory Strategy (Traditional):** Storing `data/`, `logs/` inside the project root.
    *   *Rejected because:* Makes `.gitignore` complex, complicates container mounts, and risks deleting data when cleaning the repo.
*   **Docker Volumes:** Letting Docker manage the state location.
    *   *Rejected because:* Opaque. See ADR-0006.

## 4. Consequences
*   **Positive:**
    *   Atomic "Factory Reset" capability.
    *   Simplified backup strategy (one folder to rule them all).
    *   Clear security boundaries (Code is Read-Only).
*   **Negative:**
    *   Requires strict discipline in defining `docker-compose.yml` mounts.
    *   Slightly more complex initial setup (need to create workspace folders).
