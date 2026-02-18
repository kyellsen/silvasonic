# ADR-0006: Host Bind Mounts as Default Persistence Strategy

> **Status:** Accepted • **Date:** 2026-02-18

## 1. Context & Problem
Containerized applications require persistent storage. The standard approach often defaults to "Named Volumes" (managed by the container engine). However, on an edge device where the user (researcher/developer) interacts directly with the filesystem for debugging, copying files, or manual backups, the opacity of Named Volumes is a hindrance. We need a persistence strategy that is transparent and user-friendly while complementing the [Two-Worlds architecture](0005-two-worlds-separation.md).

## 2. Decision
**We chose:** Explicit Host Bind Mounts into `SILVASONIC_WORKSPACE_PATH` for all service persistence.

**Reasoning:**
Bind mounts map a directory on the host directly into the container. This provides maximum transparency: artifacts like recordings or configuration files are immediately visible in the host's file explorer. Operations like backing up data to an external drive become simple `cp -r` commands, without requiring container-specific export tools. It also ensures the development environment structure matches the production environment exactly.

All bind mounts in the workspace MUST use the `:z` (lowercase, shared) SELinux suffix. This marks content as shared between the host and multiple containers. The use of `:Z` (private) is forbidden for shared data folders — see [Filesystem Governance](../arch/filesystem_governance.md) §4 for the full SELinux labeling policy.

> **Related Decisions:**
> *   **[ADR-0005](0005-two-worlds-separation.md):** Establishes the Two-Worlds principle (immutable code vs. mutable state) that this ADR implements at the mount level.
> *   **[ADR-0007](0007-rootless-os-compliance.md):** Covers rootless Podman and file ownership — permission management on bind mounts is handled automatically by Podman's user namespace mapping.
> *   **[ADR-0008](0008-domain-driven-isolation.md):** Defines the domain-driven directory structure within the workspace.

### 2.1. Named Volume Exceptions
Named Volumes are permitted **only** for services whose internal storage format is managed by a third-party image and must not be directly accessed by other services or the host user:

*   **`database`** (TimescaleDB/PostgreSQL) — Uses the `db-data` named volume for `/var/lib/postgresql/data`. Direct host access to PostgreSQL data files would risk corruption.
*   **`redis`** (future) — Will use a named volume for its append-only file (AOF) persistence. Same rationale as database.

These exceptions are explicitly documented. All other services MUST use host bind mounts.

## 3. Options Considered
*   **Named Volumes for Everything:**
    *   *Rejected because:* Data is hidden in engine-managed directories, hard to browse/backup for non-experts, and opaque for debugging. Contradicts the transparency goals of the Two-Worlds architecture.
*   **Tmpfs Mounts:**
    *   *Rejected because:* Data does not survive container restarts (except for specific volatile buffers).

## 4. Consequences
*   **Positive:**
    *   Immediate visibility of data on the host filesystem.
    *   Trivial backup and restore workflow (`cp -r` the workspace).
    *   Easy integration with host-side tools (e.g., system backups, `rsync`).
    *   Consistent structure between development and production environments.
*   **Negative:**
    *   Performance can be slightly lower than named volumes on some non-Linux filesystems (not an issue on our Linux/Fedora target).
    *   Requires strict discipline in `compose.yml` volume definitions and SELinux labeling (`:z` suffix).
