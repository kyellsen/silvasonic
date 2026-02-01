# ADR-0006: Use of Host Bind Mounts over Named Volumes

> **Status:** Accepted • **Date:** 2026-01-31

## 1. Context & Problem
Containerized applications require persistent storage. The standard Docker approach often defaults to "Named Volumes" (managed by the daemon). However, on an edge device where the user (researcher/developer) interacts directly with the filesystem for debugging, copying files, or manual backups, the opacity of Named Volumes (`/var/lib/docker/volumes/...`) is a hindrance. We need a persistence strategy that is transparent and user-friendly.

## 2. Decision
**We chose:** Explicit Host Bind Mounts (`/mnt/data/...`) for all persistence.

**Reasoning:**
Bind mounts map a directory on the host directly to the container. This provides maximum transparency: artifacts like recordings or logs are immediately visible in the host's file explorer. Operations like backing up data to an external drive become simple `cp -r` commands, without requiring `docker cp` or volume export tools. It also ensures the development environment structure matches the production environment exactly.

## 3. Options Considered
*   **Docker Named Volumes:**
    *   *Rejected because:* Data is hidden in system directories, often owned by root (in standard Docker), and hard to browse/backup for non-experts.
*   **Tmpfs Mounts:**
    *   *Rejected because:* Data does not survive container restarts (except for specific volatile buffers).

## 4. Consequences
*   **Positive:**
    *   Immediate visibility of data on the host.
    *   Trivial backup and restore workflow.
    *   Easy integration with host-side tools (e.g., system backups).
*   **Negative:**
    *   Performance can be slightly lower than volumes on some non-Linux FS (not an issue on Linux/Fedora).
    *   Permission management is the responsibility of the user/host (solved via ADR-0007).
