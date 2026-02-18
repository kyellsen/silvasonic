# ADR-0005: Separation of Immutable Code & Mutable State ("Two-Worlds")

> **Status:** Accepted • **Date:** 2026-02-18

## 1. Context & Problem
In an embedded/edge environment like Silvasonic, mixing application code with runtime data creates significant operational risks. If artifacts (logs, recordings, database files) are stored within the application directory, "resetting" the application to a clean state becomes impossible without losing data. Conversely, updating the application code (`git pull`) becomes risky if user data is interspersed with source files. We need a strategy to decouple the lifecycle of the software from the lifecycle of the data.

## 2. Decision
**We chose:** The "Two-Worlds" architecture principle.
*   **World A (Immutable Code):** Source code resides in `SILVASONIC_REPO_PATH` (e.g., `/mnt/data/dev/apps/silvasonic`). In production, code is baked into the container image at build time — there is no host mount. In Development Mode, source code may be mounted read-write for live-reload (see `compose.override.yml`).
*   **World B (Mutable State):** Runtime state resides in `SILVASONIC_WORKSPACE_PATH` (e.g., `/mnt/data/dev_workspaces/silvasonic`). This is the ONLY location where containers are permitted to persist user data. Bind mounts with `:z` suffix are used for SELinux compatibility.

**Reasoning:**
This strict separation treats the application code as "firmware" — immutable and easily replaceable. The state is treated as "user data" — precious and mutable. It allows us to perform a "Factory Reset" simply by deleting the workspace directory, while the code remains untouched. It also simplifies backups (backup only the workspace) and updates (`git pull` the repo without fear of conflict).

> **Follow-On Decisions:**
> *   **[ADR-0008](0008-domain-driven-isolation.md):** Defines the internal structure of the workspace (domain-driven, one directory per service).
> *   **[ADR-0009](0009-zero-trust-data-sharing.md):** Defines access control rules between services (Consumer Principle, read-only mounts).
> *   For the full normative specification see **[Filesystem Governance](../arch/filesystem_governance.md)**.

## 3. Options Considered
*   **Mixed Directory Strategy (Traditional):** Storing `data/`, `logs/` inside the project root.
    *   *Rejected because:* Makes `.gitignore` complex, complicates container mounts, and risks deleting data when cleaning the repo.
*   **Named Volumes Only:** Letting Podman manage all state via named volumes.
    *   *Rejected because:* Opaque storage location, difficult to backup and inspect. See [ADR-0006](0006-bind-mounts-over-volumes.md) for the explicit exceptions where Named Volumes are permitted (database, redis).

### 3.1. Named Volume Exceptions
Named Volumes are permitted **only** for services whose internal storage format is managed by a third-party image and must not be directly accessed by other services:
*   **`database`** (TimescaleDB/PostgreSQL) — Uses the `db-data` named volume for `/var/lib/postgresql/data`.
*   **`redis`** (future) — Will use a named volume for its append-only file (AOF) persistence.

All other services MUST use host bind mounts into the workspace.

## 4. Consequences
*   **Positive:**
    *   Atomic "Factory Reset" capability (`just reset`).
    *   Simplified backup strategy (one folder to rule them all).
    *   Clear security boundaries (code is baked into images in production).
    *   Clean `git pull` updates without data conflicts.
*   **Negative:**
    *   Requires strict discipline in defining `compose.yml` volume mounts.
    *   Slightly more complex initial setup (workspace directories must be created via `just init`).
