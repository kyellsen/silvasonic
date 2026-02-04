# Container: Controller

> **Service Name:** `controller`
> **Container Name:** `silvasonic-controller`
> **Package Name:** `silvasonic-controller`

## 1. The Problem / The Gap
*   **Dynamic Hardware:** A static `docker-compose.yml` cannot handle USB microphones being plugged/unplugged or bound to specific service instances (e.g., "Ultralytic Mic -> BatDetect Container").
*   **Self-Healing:** If a recorder crashes, something needs to detect it and restart it *intelligently* (e.g., verifying the mic is still present).
*   **Orchestration:** Users need to toggle services (e.g., "Enable BirdNET") via the UI without SSH-ing into the terminal.

## 2. User Benefit
*   **Plug-and-Play:** Automatically detects connected sensors and spins up the appropriate recording containers.
*   **Resilience:** Automatically repairs broken services.
*   **Control:** Allows enabling/disabling "heavy" features (like BirdNET) via the Dashboard to save power or CPU.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **Podman Socket**: Reads current container state (`podman.sock`).
    *   **Database Intent**: Reads `system_services` table to know what *should* be running.
    *   **Hardware Events**: Monitors `udev` or polls USB devices to detect microphone changes.
*   **Processing**:
    *   **Reconciliation Loop**: `Diff(Desired_State, Actual_State) -> Apply_Changes()`.
    *   **Device Binding**: Maps physical Serial Numbers to logical Device IDs (e.g., `SN:12345` -> `front`).
    *   **Template Spawning**: Uses the `template` images to spawn ephemeral containers for dynamic hardware.
*   **Outputs**:
    *   **Orchestration Actions**: `podman start`, `podman stop`, `podman run`.
    *   **Status Updates**: Writes current service health to Redis/DB.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **Single Control Loop**. Avoids race conditions by serializing orchestration actions.
*   **State**: **Stateless** (Authority is DB + Podman).
*   **Privileges**: **High Privilege**. Requires access to `/run/podman/podman.sock` (Group `podman`).
*   **Resources**: Low CPU, High Reliability. Must never crash.

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `PODMAN_SOCKET_PATH`: Path to the Unix socket.
    *   `HOST_DATA_DIR`: Path on the host for volume injection (e.g., `/mnt/data`).
*   **Volumes**:
    *   `/run/podman/podman.sock`: **Critical** for operation.
*   **Dependencies**:
    *   `podman` (Host binary, controlled via API/Socket).

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** process audio data.
*   **Does NOT** serve the User Interface (Web Interface job).
*   **Does NOT** store business data persistently (Database job).
*   **Does NOT** run as Root inside the container (uses Rootless Podman socket on host).
*   **Does NOT** perform heavy inference (BirdNET/BatDetect job).

## 7. Technology Stack
*   **Base Image**: `python:3.11-slim-bookworm` (Dockerfile).
*   **Key Libraries**:
    *   `sqlalchemy` + `asyncpg`: Asynchronous Database Access.
    *   `redis`: Pub/Sub Messaging for Lifecycle & Status events.
    *   `structlog`: Structured JSON logging.
    *   `psutil`: Process management.
*   **Build System**: `uv` + `Dockerfile`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Complies with "Infrastructure as Code" by reconciling against DB state. Rootless execution supported via user-mode Podman socket.
*   **Architecture Evolution**: Adopted **Profile Injection via Middleware (Environment Variables)** instead of Template Spawning. This keeps containers immutable and strengthens the Database as the single source of truth.

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **None detected.** The implementation (v0.2.x) fully aligns with the architectural pillars (Stateless, Reconcile Loop, Rootless Podman).
