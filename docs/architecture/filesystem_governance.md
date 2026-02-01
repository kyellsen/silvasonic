# Data Architecture & Filesystem Governance

> **STATUS:** NORMATIVE (Mandatory)
> **SCOPE:** System-wide (Host & Container)
> **OS TARGET:** Fedora Linux (SELinux Enforcing) with Rootless Podman

This document defines the strict governance rules for file storage, container access control, and directory structures within the Silvasonic ecosystem.

## 1. The "Two-Worlds" Architecture Principle

The system makes a strict distinction between immutable code (Repository) and mutable state (Workspace). These two worlds must never mix.

### World A: The Repository (Immutable Code)
*   **Path:** `SILVASONIC_REPO_PATH` (Default: `/mnt/data/dev/apps/silvasonic`)
*   **Content:** Source code, scripts, configuration templates, Ansible playbooks.
*   **Access Rule:**
    *   Containers have **Read-Only** access.
    *   *Exception:* In "Development Mode" (Live-Reload), containers may temporarily have write access to source files.
    *   **Strict Prohibition:** Production data (WAVs, DB files) must NEVER be stored here.

### World B: The Workspace (Mutable State)
*   **Path:** `SILVASONIC_WORKSPACE_PATH` (Default: `/mnt/data/dev_workspaces/silvasonic`)
*   **Content:** Database files, audio recordings, logs, Redis dumps, temporary buffers.
*   **Access Rule:**
    *   This is the **only** location where containers are permitted to persist data.
    *   Deleting this directory is equivalent to a "Factory Reset".

---

## 2. Domain-Driven Workspace Structure

The Workspace directory must be strictly organized by service. There is no "common dumping ground". Each service owns a dedicated directory.

### Directory Standards
The root of the Workspace must contain only folders matching the service names defined in `podman-compose.yml`.

*   **`database/`**: Exclusive for TimescaleDB/PostgreSQL data.
*   **`redis/`**: Exclusive for Redis persistence (AOF/RDB).
*   **`recorder/`**:
    *   Creates a subdirectory per microphone: `recorder/{MIC_NAME}/`
    *   Must contain `recordings/raw` inside the mic folder.
    *   Must contain `recordings/processed` inside the mic folder.
*   **`processor/`**: Must contain `artifacts` (for generated images/spectrograms).
*   **`uploader/`**: Must contain `buffer` (for temporary compression/conversions).
*   **`gateway/`, `birdnet/`, `web-interface/`**: Dedicated folders for logs or runtime configs.

### Logging Policy (Dual Logging Strategy)
*   **Archival (Mandatory)**: Every service folder **MUST** contain a `logs/` subdirectory.
    *   Application logs (e.g., Python `structlog` output) must be written to a file within this directory (e.g., `recorder/logs/recorder.log`).
    *   This ensures post-mortem analysis capability across container restarts.
*   **Real-Time (Mandatory)**: Services must **ALSO** output structured JSON logs to `stdout`.
    *   This enables the Status Board (via Podman Socket) and centralized log collectors to stream logs efficiently without file locking issues.

---

## 3. Access Control & Zero Trust (Shared Access)

Containers are not granted blanket access to the entire Workspace. The Principle of Least Privilege applies.

### The Owner Principle (Write)
*   A service is the **Owner** of its own directory.
*   Only the Owner is granted **Read-Write** access.
*   *Example:* Only the `recorder` container may write to `/mnt/.../recorder/`.

### The Consumer Principle (Read)
*   If a service needs data from another (e.g., Processor needs Recordings), that folder must be mounted **Read-Only**.
*   **Strict Rule:** A downstream service (Processor, Uploader, Dashboard) must **never** delete or modify original raw data.
*   **Deletion:** Deletion operations are exclusively reserved for the **Janitor** process (technically part of the Processor, but with explicit architectural authority).

---

## 4. OS-Compliance & Podman Configuration

As the host is Fedora with SELinux, all container definitions must adhere to the following technical requirements:

### Mount Strategy
*   **Host Bind Mounts** are mandatory.
*   **Prohibited:** Docker "Named Volumes" are forbidden for persistent data (to facilitate backup and reset operations).

### Rootless User Mapping
*   In `podman-compose.yml`, the directive `userns_mode: keep-id` is **mandatory** for any service mounting volumes.
*   This ensures files on the host are owned by the user `pi` (or the developer), not `root` or unmapped UIDs.

### SELinux Labeling
*   All Bind Mounts in the Workspace must be suffixed with `:z` (lowercase).
*   This marks content as "Shared Content", readable by multiple containers (Writer and Reader) and the host.
*   **Prohibited:** The use of `:Z` (Private Content) is forbidden for shared data folders (like `recordings`) as it blocks access for other containers.

---

## 5. Lifecycle & Initialization

The filesystem state must not be left to chance ("Docker creating folders as root").

### Init Process
*   An initialization script (`scripts/init.sh`) must run before containers start.
*   This script acts as the source of truth for the folder structure.
*   It must ensure all folders are owned by the host user and have `755` (`rwxr-xr-x`) permissions.

### Clean-Up / Reset
*   A "Factory Reset" is defined as the deletion of all content within the Workspace path.
*   The folder structure should be immediately reconstructible by re-running the Init Script.

---

## 6. Retention Policy (The Janitor)

To prevent storage exhaustion on the edge device, the `silvasonic_processor` implements a centralized background cleanup task.

### Deletion Rules
- **Non-negotiable**: Files are typically only candidates for deletion if they meet high-level state criteria in TimescaleDB.
- **Criteria**: `uploaded == true` AND all required workers in `analysis_state` (JSONB) are marked as `true`.
- **Targeting**: Deletes the oldest 15s chunks first to free space iteratively.

### Survival Thresholds
1. **Warning (>80% full)**: Delete `uploaded=true` files (oldest first). Triggers a notification via the Monitor service.
2. **Critical (>90% full)**: Delete *any* oldest files regardless of analysis/upload status to prevent recording blockage.
3. **Panic Mode (>95% full)**: Logs a critical "DATA LOSS EVENT" and performs aggressive cleanup of oldest recording chunks to survive/recover.

