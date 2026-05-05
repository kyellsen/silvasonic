# ADR-0007: Rootless Podman & OS Compliance

> **Status:** Superseded • **Date:** 2026-01-31 • **Superseded:** 2026-02-17

## 1. Context & Problem
Running containers as `root` is a security risk and on modern generic Linux systems (like Fedora), it complicates file ownership. Files created by a root-container often end up owned by `root` on the host, modifying them requires `sudo`, leading to "Permission Hell" for the developer. Furthermore, Fedora enforces SELinux strictly, which blocks containers from accessing arbitrary host paths unless correctly labeled.

## 2. Decision

### Original Decision (Superseded)
1.  **Rootless Podman:** Executed as the user `pi` (or current dev user).
2.  **User Namespace ID Mapping:** `userns_mode: keep-id`.
3.  **SELinux Labeling:** Use of `:z` (shared) suffix on mounts.

### Revised Decision (2026-02-17)
The strict `USER pi` + `keep-id` approach was replaced with a pragmatic Podman-only strategy:

1.  **No `USER` directive in Containerfiles** — containers run as root inside.
2.  **No `userns_mode: keep-id`** — unnecessary complexity (see below).
3.  **SELinux Labeling:** `:z` suffix on bind mounts is retained.

**Why this works (Podman rootless):**
*   Podman rootless automatically maps container-root to the host user via user namespaces. Files on bind mounts appear owned by the calling user — no `keep-id` needed.
*   Root inside the container has automatic access to mounted devices (`/dev/snd`) without UID conflicts.
*   Works identically on Raspberry Pi, Fedora Workstation, and any other Linux system with Podman.

## 3. Options Considered
*   **Docker Workspace:** Rejected. Requires root daemon, causes permission mapping hell across systems.
*   **Podman Rootful:** Rejected. Direct violation of security policies.

## 4. Consequences
*   **Positive:**
    *   No UID/GID conflicts between different Linux systems.
    *   Simpler Containerfiles (no user creation logic).
    *   Seamless file ownership on bind mounts (Podman rootless).
*   **Negative:**
    *   Podman-only — no fallback to other container engines.

## 5. Host Configuration (Required)
The user running Podman must be a member of the following groups:

1.  **User Groups** (cross-distro, exist on all Linux distributions):
    *   `audio` (Sound card / ALSA access — required for `/dev/snd`)
    *   `dialout` (Serial / USB-UART access)
2.  **Linger:** Ensure user services run without an active session:
    *   `loginctl enable-linger <user>`

> [!NOTE]
> RPi-specific groups like `gpio`, `spi`, and `i2c` are **NOT** required by Silvasonic.
> The Recorder uses only ALSA (via FFmpeg) for audio capture.
> Future sensor extensions (BME680, SPS30) may require I²C/SPI — handle at that time.

## 6. Privileged Exceptions

> [!CAUTION]
> `privileged: true` grants the container full access to host devices and capabilities. It is an explicit exception to the general rootless principle and MUST be limited to the services listed below.

The following services are permitted to run with `privileged: true`:

| Service        | Reason                                                                                                                     | Alternatives Considered                                                                                                                                      |
| -------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Controller** | Manages the host Podman socket (DooD pattern, see ADR-0013). Must create Tier 2 containers with arbitrary device mappings and read `/proc/asound` + `/sys/class/sound` for device scanning. | Specific capabilities (`CAP_SYS_ADMIN`) — insufficient for full socket access and sysfs traversal.                                                                               |
| **Recorder**   | Requires direct ALSA access to `/dev/snd` character devices for audio capture. `privileged: true` eliminates cross-distro issues (GID differences, SELinux labeling) without complex runtime detection. | `group_add` with numeric GID + `security_opt: [label=disable]` — worked but required host-side env var injection (`HOST_AUDIO_GID`, `HOST_SELINUX`) and runtime detection logic. Rejected for KISS. |

> [!NOTE]
> Under Podman rootless, `privileged: true` does **not** grant root access to the host.
> The container still runs inside a user namespace — the actual security boundary is Podman's rootless sandbox, not the container's privilege level.

**All other services** (Database, Gateway, Processor, Redis, Web-Interface, and all non-hardware Tier 2 services like BirdNET, BatDetect, Weather) **MUST NOT** use `privileged: true`.
