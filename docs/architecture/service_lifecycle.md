# Service Lifecycle & Orchestration

This document defines the mechanisms by which Silvasonic services are managed, spawned, and healed.

## 1. Service Orchestration Strategy

Silvasonic uses a modular architecture where a supervisor (the **Controller**) manages the lifecycle of dynamic hardware-linked containers and system-wide functional services.

### Service Hub & Registry
Managed via the `ServiceManager` in the Controller, the system uses a **Config-as-Code** approach.
- **Registry Management**: Interfaces with database-backed service definitions (e.g., `system_services` table) or declarative manifests.
- **Validation**: Uses Pydantic models to ensure configuration integrity before spawning containers.
- **Lifecycle Control**: Controls container lifecycles via the Podman API/Socket, using mandatory labels (`managed_by=silvasonic-controller`) for discovery.

### Service Tiers & Criticality
The system is divided into two distinct tiers based on **Criticality** and **Management Strategy**.

#### Tier 1: Infrastructure (Managed by Podman Compose)
These services are static, boot with the host, and provide the foundation for the appliance. They must be resilient to application-level crashes.

| Service | Role | Criticality | Optionality |
| :--- | :--- | :--- | :--- |
| **database** | State Store | **CRITICAL** | Required |
| **gateway** | Ingress/Auth | **CRITICAL** | Required |
| **redis** | Msg Broker | **CRITICAL** | Required |
| **controller** | Orchestrator | **CRITICAL** | Required |
| **web_interface** | Dashboard | Life Support | Optional (Default: ON) |
| **monitor** | Watchdog | Life Support | Optional (Default: ON) |
| **tailscale** | VPN | Life Support | Optional (Default: ON) |

> [!NOTE]
> **"Life Support" Services**: Components like `web_interface`, `monitor`, and `tailscale` run in Tier 1 so they remain accessible even if the `controller` crashes or restarts. They are toggled via `.env` variables (e.g. `ENABLE_TAILSCALE=false`) but are enabled by default.

#### Tier 2: Application (Managed by Controller)
These services contain the core business logic (Recording, Processing, Analysis). Their lifecycle is dynamic, managed by the Controller to support hot-plugging hardware and error recovery.

| Service | Role | Criticality |
| :--- | :--- | :--- |
| **recorder** | Audio Capture | **High** (Dynamic/No DB) |
| **processor** | Data Mgmt | **High** (Always Running) |
| **uploader** | Sync | **Medium** (Job based) |
| **birdnet** | Inference | **Low** (Optional Feature) |
| **batdetect** | Inference | **Low** (Optional Feature) |
| **weather** | Env Data | **Low** (Optional Feature) |

### The "Build Template" Pattern
Silvasonic uses the **Template Pattern** for services that require dynamic scaling or hardware-specific affinity (e.g., `recorder`, `birdnet`, `weather`, `batdetect`).
1. **Build Step**: These services are defined in `podman-compose.yml` to ensure their images are built/updated during `podman-compose up --build`.
2. **Immediate Exit**: Their entrypoint is set to `["/bin/true"]` and `restart: "no"`. They are *expected* to show as **Exited (0)** in `podman ps -a`.
3. **Dynamic Spawning**: The **Controller** uses these pre-built images as the "source" to spawn active sibling containers (e.g., `silvasonic_recorder_front`) using the host's Podman socket.
4. **Benefit**: Decouples the build process from the dynamic runtime, allowing multiple microphones or processing instances to share a single validated image.

### Reconciliation Loop & Self-Healing
A watchdog mechanism periodically audits running containers against the expected state.
- **Detection**: If a container is expected but missing, a restart is triggered.
- **Anti-Flapping**: Implements exponential backoff to prevent restart loops.
    - **Formula**: `wait_time = min(300, 5 * (2 ** failure_count))`
    - **Stability**: A container is considered "Stable" after 5 minutes of uptime, which resets the failure counter.
- **Hardware Binding**: Re-scans hardware via `DeviceManager` during recovery.
    - **Identity Persistence**: Devices are bound by **Serial Number** (e.g. `123456` -> `front`), NOT by USB port or ALSA path.
    - **Replug Safety**: Unplugging and replugging the same mic (even into a different port) preserves the `front` identity and recording directory.

## 2. Service State Persistence

To ensure system state survives power cycles without host-level intervention:
- **Registry**: The `ServiceManager` maintains a hardcoded `REGISTRY` of managed services (e.g., BirdNET, Weather, Uploader, Icecast) with default `enabled` states.
- **Desired State Determination**:
    1. Start with the **Registry default** (e.g., `birdnet` is `enabled=True` by default).
    2. Override with the `system_services` table (`enabled` column).
- **Control Flow**:
    - **User**: Toggles switch in Dashboard UI -> Updates `system_services` table.
    - **Controller**: Periodically checks `system_services` vs. `podman ps`.
- **Service Reconciliation Loop**:
    1. **Fetch Desired**: Consult Registry + DB.
    2. **Fetch Actual**: Scan running containers using the `silvasonic.service` label via `PodmanOrchestrator.list_active_services()`.
    3. **Reconcile**: 
        - If `Desired == Enabled` and `Actual == Not Running` -> **Start Service**.
        - If `Desired == Disabled` and `Actual == Running` -> **Stop Service**.
- **Discovery**: Containers are identified by the label `silvasonic.service={service_name}`, allowing the Controller to track services it spawned even after a restart.
- **Dynamic Host Path Injection**: In development or non-standard environments (e.g., custom data directories), the Controller MUST inject host paths using the `HOST_SILVASONIC_DATA_DIR` environment variable into child container mounts. This prevents "No such file or directory" errors during `podman run` when the container attempts to mount host paths that differ from the hardcoded `/mnt/data/services/silvasonic` default.
- **Log Persistence & Dual Logging**:
    - **Strategy**: Services use a "Dual Logging" approach (defined in `silvasonic.core.logging`).
        1. **Stdout (JSON)**: For real-time monitoring via Podman API and Status Board.
        2. **File (JSON)**: For archival and post-mortem analysis.
    - **Injection**: The Controller injects `LOG_DIR=/var/log/silvasonic` into spawned containers.
    - **Mounts**: It MUST mount `${HOST_SILVASONIC_DATA_DIR}/{service}//logs:/var/log/silvasonic:z`.
    - **Result**: Even if a container restarts, the logs are preserved on the host NVMe.
- **Recovery**: This mechanism ensures that default services (like Weather and BirdNET) start automatically on a clean database install without requiring manual activation via the Dashboard.
