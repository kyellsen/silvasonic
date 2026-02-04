# Container: Redis

> **Service Name:** `redis`
> **Container Name:** `silvasonic-redis`
> **Package Name:** `silvasonic-redis` (Docker Image Only)

## 1. The Problem / The Gap
*   **Real-time Updates:** Polling the database for every UI update (e.g., "Is the recorder running?") is inefficient and adds latency.
*   **Decoupling:** Services need to communicate (e.g., "Restart Command") without direct HTTP coupling.

## 2. User Benefit
*   **Snappy UI:** The dashboard updates instantly when events happen (Pub/Sub).
*   **System Responsiveness:** Commands like "Stop Recording" propagate immediately via control channels.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Message Broker**: Hosting Pub/Sub channels and Streams for inter-service communication.
    *   *See [Messaging Patterns](../../docs/architecture/messaging_patterns.md) for full protocol definitions.*
*   **Transient State**: Storing short-lived keys (e.g., `status:recorder:front` TTL 10s).
*   **Memory Management**: Max memory 64mb, LRU eviction policy.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **High**. Single-threaded but extremely fast Event Loop.
*   **State**: **Mixed**.
    *   **Persistence**: Explicitly **DISABLED** (`save ""`, `appendonly no`).
    *   **Streams**: Runtime persistence only. Pruned by `MAXLEN` or memory cap.
*   **Privileges**: **Rootless**.
*   **Resources**: Very Low RAM (Capped at 64MB).

## 5. Configuration & Environment
*   **Environment Variables**:
    *   Standard Redis Config.
*   **Volumes**:
    *   `./services/redis/redis.conf` -> `/usr/local/etc/redis/redis.conf` (Read Only).
    *   `${SILVASONIC_WORKSPACE_PATH}/redis` -> `/data` (Mounted but not used for persistence).
*   **Dependencies**:
    *   None.

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** store recordings.
*   **Does NOT** replace the Database (no persistent business data).
*   **Does NOT** handle authentication/authorization logic.
*   **Does NOT** serve HTTP traffic (Gateway job).
*   **Does NOT** process complex analytical queries.

## 7. Technology Stack
*   **Base Image**: `redis:alpine`.
*   **Key Libraries**:
    *   Redis Server 7.x.
*   **Build System**: Docker Hub Upstream.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Standard use of Redis for Broker pattern. Persistence disabled for pure hygiene.
*   **Alternatives**: RabbitMQ (Too heavy), ZeroMQ (Too complex/no persistence).

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** Docker Compose mounts a data volume (`/data`), but `redis.conf` explicitly disables persistence (`save ""`). The volume is currently unused.
