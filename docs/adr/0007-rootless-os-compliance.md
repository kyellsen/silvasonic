# ADR-0007: Rootless Podman & OS Compliance

> **Status:** Accepted • **Date:** 2026-01-31

## 1. Context & Problem
Running containers as `root` is a security risk and on modern generic Linux systems (like Fedora), it complicates file ownership. Files created by a root-container often end up owned by `root` on the host, modifying them requires `sudo`, leading to "Permission Hell" for the developer. Furthermore, Fedora enforces SELinux strictly, which blocks containers from accessing arbitrary host paths unless correctly labeled.

## 2. Decision
**We chose:** 
1.  **Rootless Podman:** Executed as the user `pi` (or current dev user).
2.  **User Namespace ID Mapping:** `userns_mode: keep-id`.
3.  **SELinux Labeling:** Use of `:z` (shared) suffix on mounts.

**Reasoning:**
This configuration ensures that files created by the application inside the container appear as owned by the standard user (`pi`) on the host. This allows the user to access, delete, or move these files via SCP, SMB, or the shell without needing `sudo`. The `:z` label correctly instructs SELinux that these files are safe to be shared between the container workspace and the host.

## 3. Options Considered
*   **Rootful Docker:** 
    *   *Rejected because:* Security risk, files owned by root on host.
*   **Privileged Mode:**
    *   *Rejected because:* Breaks isolation, bad practice.
*   **Disabling SELinux:**
    *   *Rejected because:* Weakens host security posture significantly.

## 4. Host Configuration (Mandatory)
To ensure the rootless architecture functions correctly, the host system (Raspberry Pi OS / Fedora) **MUST** be configured as follows:

1.  **User Groups:** The user `pi` (or service user) MUST be a member of:
    *   `plugdev` (USB access)
    *   `dialout` (Serial access)
    *   `audio` (Sound card/ALSA access)
    *   `gpio` (GPIO access)
2.  **Sysctl:** Allow unprivileged ports for Caddy (Gateway):
    *   `sysctl -w net.ipv4.ip_unprivileged_port_start=80`
3.  **Linger:** Ensure user services run without an active session:
    *   `loginctl enable-linger pi`

## 5. Consequences
*   **Positive:**
    *   Seamless file access for the user (No `sudo rm` needed).
    *   High security posture (unprivileged containers).
    *   Full compatibility with Enterprise Linux standards.
*   **Negative:**
    *   Requires explicit configuration in `podman-compose.yml`.
    *   Ports < 1024 cannot be bound without `sysctl` modification (addressed in config).
