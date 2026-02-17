# ADR-0007: Rootless Podman & OS Compliance

> **Status:** Superseded • **Date:** 2026-01-31 • **Superseded:** 2026-02-17

## 1. Context & Problem
Running containers as `root` is a security risk and on modern generic Linux systems (like Fedora), it complicates file ownership. Files created by a root-container often end up owned by `root` on the host, modifying them requires `sudo`, leading to "Permission Hell" for the developer. Furthermore, Fedora enforces SELinux strictly, which blocks containers from accessing arbitrary host paths unless correctly labeled.

## 2. Original Decision (Superseded)
1.  **Rootless Podman:** Executed as the user `pi` (or current dev user).
2.  **User Namespace ID Mapping:** `userns_mode: keep-id`.
3.  **SELinux Labeling:** Use of `:z` (shared) suffix on mounts.

## 3. Revised Decision (2026-02-17)
The strict `USER pi` + `keep-id` approach was replaced with a pragmatic Podman-only strategy:

1.  **No `USER` directive in Containerfiles** — containers run as root inside.
2.  **No `userns_mode: keep-id`** — unnecessary complexity (see below).
3.  **SELinux Labeling:** `:z` suffix on bind mounts is retained.

**Why this works (Podman rootless):**
*   Podman rootless automatically maps container-root to the host user via user namespaces. Files on bind mounts appear owned by the calling user — no `keep-id` needed.
*   Root inside the container has automatic access to mounted devices (`/dev/snd`, GPIO) without UID conflicts.
*   Works identically on Raspberry Pi, Fedora Workstation, and any other Linux system with Podman.

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
    *   No UID/GID conflicts between different Linux systems.
    *   Simpler Containerfiles (no user creation logic).
    *   Seamless file ownership on bind mounts (Podman rootless).
*   **Negative:**
    *   Podman-only — no fallback to other container engines.

## 6. Privileged Exceptions

> [!CAUTION]
> `privileged: true` grants the container full access to host devices and capabilities. It is an explicit exception to the general rootless principle and MUST be limited to the services listed below.

The following services are permitted to run with `privileged: true`:

| Service        | Reason                                                                                                                     | Alternatives Considered                                                                                                                                      |
| -------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Controller** | Manages the host Podman socket (DooD pattern, see ADR-0013). Must create Tier 2 containers with arbitrary device mappings. | Specific capabilities (`CAP_SYS_ADMIN`) — insufficient for full socket access.                                                                               |
| **Recorder**   | Direct access to audio hardware (`/dev/snd`, ALSA subsystem) and GPIO.                                                     | Specific device mounts + `group_add: [audio]` — works for audio but not for all GPIO/USB scenarios. Keeping `privileged` for robustness on diverse hardware. |

**All other services** (Database, Gateway, Processor, Redis, Web-Interface, Tailscale, and all non-hardware Tier 2 services like Uploader, BirdNET, BatDetect, Weather) **MUST NOT** use `privileged: true`.
