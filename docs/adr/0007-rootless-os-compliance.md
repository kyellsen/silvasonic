# ADR-0007: Rootless Podman & OS Compliance

> **Status:** Superseded • **Date:** 2026-01-31 • **Superseded:** 2026-02-17

## 1. Context & Problem
Running containers as `root` is a security risk and on modern generic Linux systems (like Fedora), it complicates file ownership. Files created by a root-container often end up owned by `root` on the host, modifying them requires `sudo`, leading to "Permission Hell" for the developer. Furthermore, Fedora enforces SELinux strictly, which blocks containers from accessing arbitrary host paths unless correctly labeled.

## 2. Original Decision (Superseded)
1.  **Rootless Podman:** Executed as the user `pi` (or current dev user).
2.  **User Namespace ID Mapping:** `userns_mode: keep-id`.
3.  **SELinux Labeling:** Use of `:z` (shared) suffix on mounts.

## 3. Revised Decision (2026-02-17)
The strict `USER pi` + `keep-id` approach was replaced with a pragmatic cross-platform strategy:

1.  **No `USER` directive in Dockerfiles** — containers run as root inside.
2.  **No `userns_mode: keep-id`** — this is Podman-only and breaks Docker compatibility.
3.  **SELinux Labeling:** `:z` suffix on bind mounts is retained.

**Why this works:**
*   **Podman rootless:** Automatically maps container-root to the host user via user namespaces. Files on bind mounts appear owned by the calling user — no `keep-id` needed.
*   **Docker:** Container-root equals host-root. Acceptable for Silvasonic as an edge device with no security-critical data or network exposure.
*   **Cross-platform:** Works identically on Raspberry Pi, Fedora Workstation, and any other Linux system with either container engine.
*   **Hardware access:** Root inside the container has automatic access to mounted devices (`/dev/snd`, GPIO) without UID conflicts.

## 4. Host Configuration (Still Recommended)
The following host configuration remains useful for optimal operation:

1.  **User Groups:** The user `pi` (or service user) SHOULD be a member of:
    *   `audio` (Sound card/ALSA access)
    *   `plugdev` (USB access)
    *   `dialout` (Serial access)
    *   `gpio` (GPIO access, Raspberry Pi only)
2.  **Linger:** Ensure user services run without an active session:
    *   `loginctl enable-linger pi`

## 5. Consequences
*   **Positive:**
    *   Works with both Podman and Docker without configuration changes.
    *   No UID/GID conflicts between different Linux systems.
    *   Simpler Dockerfiles (no user creation logic).
    *   Seamless file ownership on bind mounts (Podman rootless).
*   **Negative:**
    *   Docker users run as host-root inside containers (acceptable trade-off for edge device).
