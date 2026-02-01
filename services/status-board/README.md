# Container: Status Board

> **Service Name:** `status-board`
> **Container Name:** `silvasonic-status-board`
> **Package Name:** `silvasonic-status-board`

## 1. The Problem / The Gap
*   **Visibility Blindspots:** Without a dedicated monitor, checking if the recorder is running requires SSH-ing into the box or trusting a black box.
*   **Dev Productivity:** Developers need instant feedback on system health (CPU, Temp, Docker Container states) without sifting through logs manually.

## 2. User Benefit
*   **"Heads-Up" Display:** Instant confirmation that the system is recording and healthy.
*   **Safety:** A passive monitoring tool that cannot accidentally stop a recording (unlike the main Admin UI).

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **Podman/Docker Socket**: Reads container states (`silvasonic-recorder` status).
    *   **System Stats**: Reads CPU/RAM/Disk usage from host (via mapped paths or Python libs).
    *   **Database/Redis**: Reads configuration and heartbeat signals.
*   **Processing**:
    *   **Visualization**: Renders servers-side HTML (Jinja2) for low-latency status.
    *   **Polling Endpoint**: Provides HTMX fragments for auto-refreshing UI.
*   **Outputs**:
    *   **HTML/CSS**: Status Dashboard.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **Async**. Uses FastAPI/Uvicorn.
*   **State**: **Stateless**.
*   **Privileges**: **Socket Access**. Requires access to `/run/podman/podman.sock` (or Docker equivalent) and appropriate SELinux labeling (`label=disable`).
*   **Resources**: Low.

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `DEV_MODE`: Must be "true" (Failsafe to prevent production deployment if intended only for raw dev access).
    *   `POSTGRES_HOST`, `REDIS_HOST`.
*   **Volumes**:
    *   `/run/podman/podman.sock` -> `/run/podman/podman.sock` (Read-only access ideally, but often RW for libraries).
*   **Dependencies**:
    *   `silvasonic-core`.
    *   `fastapi`, `uvicorn`, `jinja2`.

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** control the recorder (Start/Stop is forbidden).
*   **Does NOT** provide playback of recordings (Web Interface job).
*   **Does NOT** manage users.
*   **Does NOT** write to the database (Read-Only principle).

## 7. Technology Stack
*   **Base Image**: `python:3.11-slim-bookworm`.
*   **Key Libraries**:
    *   FastAPI.
    *   HTMX (Frontend).
    *   DaisyUI/Tailwind (CSS).
*   **Build System**: `uv` + `Dockerfile`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Strict separation of "Monitoring" vs "Control" is a good safety pattern for autonomous field devices.
*   **Alternatives**: Grafana/Prometheus (Too heavy for a Raspberry Pi field unit), Glances (Not custom enough for specific app states).

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** None detected.
