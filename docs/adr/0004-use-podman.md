# ADR-0004: Use Podman instead of Docker

> **Status:** Accepted • **Date:** 2026-01-31

## 1. Context & Problem
We need a container runtime environment for developing, testing, and running the Silvasonic microservices. The standard solution in the industry is Docker. However, the development environment relies on Fedora Workstation, and security and system integration are high priorities. We need to decide whether to use Docker or an alternative like Podman.

## 2. Decision
**We chose:** Podman (and `podman-compose`)

**Reasoning:**
*   **Rootless by Design:** Podman allows running containers as a non-privileged user (rootless mode). This is a significant security advantage as it prevents container processes from having root privileges on the host system.
*   **Fedora Native:** The primary development environment is Fedora Workstation. Podman is the native, default container engine in Fedora/RHEL, ensuring first-class support and seamless OS integration.
*   **Daemonless Architecture:** Unlike Docker, Podman does not rely on a central daemon (dockerd) running in the background. This eliminates a single point of failure and reduces idle resource consumption.
*   **Reliable Edge Deployment (Systemd):** Podman is designed to work closely with systemd. It can generate systemd unit files (`podman generate systemd`) or purely Quadlet files. This is critical for our edge device use case, ensuring all containers automatically and securely restart after a power failure without needing a complex orchestration layer.
*   **Docker Compatibility:** Podman offers a CLI that is identical to Docker's for most commands. `alias docker=podman` works for the vast majority of workflows, lowering the barrier to entry.
    *   *Update (2026-02-17):* While Podman is the default, we allow developers to use Docker by setting `SILVASONIC_CONTAINER_ENGINE=docker` in their `.env` file. The `Makefile` adapts the commands accordingly.

## 3. Options Considered
*   **Docker (Docker CE / Docker Desktop):** Rejected. While it is the industry standard, the requirement for a root-privileged daemon creates security concerns. Docker Desktop also introduces licensing complexities for some use cases, and Docker CE's integration with systemd is less native than Podman's.
*   **Nerdctl + Containerd:** Rejected. While strictly OCI-compliant and powerful, the tooling and developer experience (DX) are not as mature or user-friendly as Podman's CLI for a workstation environment.

## 4. Consequences
*   **Positive:**
    *   Improved security posture through rootless containers.
    *   No persistent daemon overhead.
    *   Better alignment with the OS (Fedora) and init system (systemd).
    *   High reliability on edge devices (automatic restart after power loss).
*   **Negative:**
    *   Some legacy tools that strictly rely on the Docker socket might require configuration (e.g., enabling the `podman.socket` service).
    *   `podman-compose` is used instead of `docker-compose`, which may have minor differences in less common feature implementations, though it covers our needs.
