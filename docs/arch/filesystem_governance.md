# Data Architecture & Filesystem Governance

> **STATUS:** NORMATIVE (Mandatory)
> **SCOPE:** System-wide (Host & Container)
> **OS TARGET:** Fedora Linux (SELinux Enforcing) with Rootless Podman

This document defines the strict governance rules for file storage, container access control, and directory structures within the Silvasonic ecosystem.

## 1. The "Two-Worlds" Architecture Principle

> See **[ADR-0005](../adr/0005-two-worlds-separation.md)** for the architectural decision behind this principle.

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
*   **Content:** Audio recordings, configuration files, service-specific data.
*   **Access Rule:**
    *   This is the **only** location where containers are permitted to persist data.
    *   Deleting this directory is equivalent to a "Factory Reset".

---

## 2. Domain-Driven Workspace Structure

The Workspace directory must be strictly organized by service. There is no "common dumping ground". Each service owns a dedicated directory.

### Directory Standards
The root of the Workspace must contain only folders matching the service names defined in `compose.yml`. The `init.py` script creates only these top-level service directories. All internal structure within a service directory is created **dynamically at runtime** by the respective service or the Controller.

*   **`controller/`**:
    *   Orchestration state and configuration.
    *   Internal structure is created by the Controller at startup.

*   **`recorder/`**:
    *   Internal structure is created **dynamically by the Controller** when a new microphone is registered.
    *   Creates a subdirectory per microphone: `recorder/{MIC_NAME}/`
    *   Must contain `.buffer/recordings/raw` inside the mic folder.
    *   Must contain `.buffer/recordings/processed` inside the mic folder.
    *   Must contain `data/recordings/raw` inside the mic folder.
    *   Must contain `data/recordings/processed` inside the mic folder.

> **NOTE:** `database` uses a **Named Volume** and does not reside in the user-accessible Workspace to prevent permission errors and accidental corruption.

### Logging Policy
*   Services must output structured JSON logs to `stdout`.
*   The container runtime (Podman) is responsible for capturing, rotating, and persisting logs.
*   There are **no** file-based log directories in the Workspace.

---

## 3. Access Control & Zero Trust (Shared Access)

Containers are not granted blanket access to the entire Workspace. The Controller, as the system orchestrator, has elevated privileges, while other services operate under strict scoping.

### The Controller Authority (System Orchestrator)
*   The **Controller** service is the "Boss" of the system.
*   It is explicitly granted **Read-Write** access to all service workspace directories (e.g., `recorder/`) to manage configuration, create directory structures (e.g., `{MIC_NAME}` folders), and orchestrate lifecycles.

### Service Scoping (The Worker Principle)
*   Worker services (like `recorder`) are scoped to their specific domain.
*   They have **Read-Write** access **only** to their own root folder.
*   *Example:* The `recorder` container writes its data into `/recorder/{MIC_NAME}/`, but the directory structure is provisioned by the Controller.

### The Consumer Principle (Read)
*   If a service needs data from another, that folder must be mounted **Read-Only**.
*   **Strict Rule:** A downstream service must **never** delete or modify original raw data.

---

## 4. OS-Compliance & Podman Configuration

As the host is Fedora with SELinux, all container definitions must adhere to the following technical requirements:

### Mount Strategy
*   **Host Bind Mounts** are mandatory for all User Data (Recordings, Configs).
*   Each service mounts its entire Workspace subdirectory as a single volume (e.g., `workspace/recorder:/app/workspace:z`).
*   **Named Volumes:** Are permitted **only** for `database` internal state.

### SELinux Labeling
*   All Bind Mounts in the Workspace must be suffixed with `:z` (lowercase).
*   This marks content as "Shared Content", readable by multiple containers (Writer and Reader) and the host.
*   **Prohibited:** The use of `:Z` (Private Content) is forbidden for shared data folders (like `recordings`) as it blocks access for other containers.

---

## 5. Lifecycle & Initialization

The filesystem state must not be left to chance ("container runtime creating folders as root").

### Init Process
*   An initialization script (`scripts/init.py`) must run before containers start.
*   This script creates the **service root directories** only (`controller/`, `recorder/`).
*   Internal directory structures within each service are created dynamically by the Controller or the respective service at runtime.
*   It must ensure all folders are owned by the host user and have `755` (`rwxr-xr-x`) permissions.

### Clean-Up / Reset
*   A "Factory Reset" is defined as the deletion of all content within the Workspace path.
*   The folder structure should be immediately reconstructible by re-running the Init Script.