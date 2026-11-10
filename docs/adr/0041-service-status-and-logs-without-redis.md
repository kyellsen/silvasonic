# ADR-0041: Service Status and Logs without Redis

> **Status:** Proposed • **Date:** 2026-11-10 • **Amends on acceptance:** [ADR-0017](0017-service-state-management.md), [ADR-0019](0019-unified-service-infrastructure.md), [ADR-0022](0022-live-log-streaming.md)

## 1. Context & Problem

Redis carries four things on a station, all of them small and short-lived ([Messaging Patterns §3](../arch/messaging_patterns.md)):

| Use | Written by | Read by |
| --- | --- | --- |
| Status snapshot per service (`SET silvasonic:status:<id>` with a TTL) | every service, every 10 s | `web-mock`, and the Controller's watchdog |
| Live status (`PUBLISH silvasonic:status`) | every service | `web-mock` |
| Live logs (`PUBLISH silvasonic:logs`) | the Controller, from `podman logs` | `web-mock` |
| Wake-up (`PUBLISH silvasonic:nudge`) | the interface, after a change | the Controller |

Three things have changed since ADR-0017 chose Redis for them:

*   **The readers are about to be replaced.** `web-mock` goes with v0.11.0. The API service ([ADR-0032](0032-api-first-station-contract.md)) becomes the reader of status and logs, and it is not built yet. Built on Redis first, it would be rebuilt afterwards.
*   **Redis is in the Recorder's supervision path.** The Controller reads each Recorder's heartbeat from Redis and replaces a Recorder whose heartbeat is stale. The Messaging Patterns call the critical path free of Redis; this watchdog is the exception.
*   **A broker is a service to run.** It is one more container to start, secure, update and harden on every station, for a few kilobytes that live ten seconds. v1.0.0 plans two tasks only because it exists (recovery from a Redis outage, a review of Redis access).

The wake-up has become redundant on its own: the Controller reconciles every second (`SILVASONIC_RECONCILE_INTERVAL_S`), so a change written to the database takes effect within one interval with or without it.

## 2. Decision

**We chose:** a runtime directory in memory instead of a broker. Each service writes its status to a file of its own; the Controller writes the logs it already reads beside it; readers read files. Redis leaves the station.

**Reasoning:**

*   **One directory, in memory.** `SILVASONIC_RUNTIME_PATH` points at a tmpfs directory of the station user (`$XDG_RUNTIME_DIR/silvasonic`). Nothing in it is written to the storage medium, and nothing in it survives a reboot; both are what status and live logs need.
*   **One subdirectory per service instance:**

    ```
    <runtime>/<instance_id>/status.json   # the heartbeat, replaced atomically
    <runtime>/<instance_id>/log.jsonl     # recent log lines, one JSON object each
    ```

    The instance id is the one of ADR-0019 (`controller`, `birdnet`, a microphone's `hardware_id`).
*   **Status is the heartbeat, unchanged.** `silvasonic.core.heartbeat` stays the only writer and the only place that changes: it writes the payload of ADR-0019 §2.4 to a temporary name and renames it onto `status.json`. A reader therefore never sees half a file. The write stays best-effort: if it fails, the service carries on.
*   **A service can write its own status and nothing else.** Its container mounts only its own subdirectory read-write. The Controller and the API mount the whole directory read-only; the Controller additionally writes the log files. With Redis, any service could overwrite any key.
*   **Readers judge freshness, with their own clock.** Redis expired a key after its TTL; a file stays. A reader treats a status as absent once it has not changed for the TTL (three heartbeat intervals, as before). It measures that span with its own monotonic clock from the moment it sees the file change, and falls back to the file's modification time only right after its own start. The wall clock of a station without a battery-backed clock jumps when the time is first synchronised, and a comparison of wall-clock timestamps would then call every service stale at once.
*   **Watching is optional.** A reader may poll the directory or watch it with inotify. Reading costs one `stat` per service, and the Controller already loops every second.
*   **Logs change their transport, not their source.** The Controller's log forwarder keeps reading `podman logs` of the containers it manages and appends each line to that instance's `log.jsonl`. At a size limit the file becomes `log.jsonl.1` and a new one starts, so an instance holds at most two files. The API tails them and serves Server-Sent Events. A client that connects late now gets the recent lines, which Pub/Sub could not give. Where the lines come from once systemd supervises the services is decided with ADR-0042.
*   **The wake-up is dropped.** The API writes desired state to the database, and the next reconciliation picks it up.
*   **New detections reach the browser from the database.** Nothing publishes them today; the API reads them where they are stored.

## 3. Options Considered

*   **Keep Redis (ADR-0017):** Rejected for the station. Its reasons were sound for a web interface that subscribes to a broker; the API can read a directory as easily, and the broker then has no reader left that needs it.
*   **A Unix datagram socket owned by the API:** Rejected. It has one reader, and the Controller's watchdog needs the status too. A reader that starts later finds no snapshot. Whether SELinux lets one container send to another's socket across their separate categories is unverified.
*   **Status rows in the station database:** Rejected. The Recorder has no database access ([ADR-0013](0013-tier2-container-management.md)). Every service would take the database's single write lock every ten seconds (ADR-0037) and wear the storage medium for data that is worthless after thirty.
*   **The API polls each service's health endpoint:** Rejected. The API would need a network path to every service, the Recorder included, and the health endpoint answers "is it alive", not "what is it doing" (ADR-0019 §2.3).
*   **journald as the log source now:** Deferred to ADR-0042. Reading the user's journal from inside a rootless container needs access the API should not have, and the source changes anyway once systemd starts the services.
*   **Another broker (MQTT, NATS):** Rejected. It replaces the service this decision removes.
*   **Tailing the container runtime's own log files (rejected in ADR-0022):** Still rejected, for the reasons given there. The files here are ours: written for this purpose, at a path we define, by the component that already reads the logs.

## 4. Consequences

*   **Positive:**
    *   One container, one image and one port fewer on every station, and no broker to secure or update.
    *   No path of the station depends on a broker any more, the Recorder's watchdog included. The Recorder loses its one network dependency.
    *   Status and recent logs can be read on the station with `cat`.
    *   Unit and integration tests need no Redis container.
*   **Negative:**
    *   The change touches about two dozen source files and three dozen test files, among them system and smoke tests that run on images. It stays cheap only while the core heartbeat is the single writer.
    *   Every container needs one more mount, in `compose.yml` and in the Controller's container specifications.
    *   Staleness is now logic in each reader instead of a property of the store.
    *   A change of desired state waits for the next reconciliation. If the interval is ever raised to save CPU, the latency rises with it, and a wake-up needs a new mechanism.
    *   The memory Redis frees is small and unmeasured; this decision is about moving parts, not about RAM.
*   **Not ported:** `web-mock`, which v0.11.0 replaces.
*   **On acceptance these documents change:**
    *   ADR-0017: where actual state lives; the Reconcile-Nudge.
    *   ADR-0019: §2.2 and §2.3 (the Redis connection and the heartbeat channel), §2.5 (`silvasonic.core.redis`).
    *   ADR-0022: the transport of live logs.
    *   `docs/arch/messaging_patterns.md`, `docs/arch/filesystem_governance.md` (the runtime directory), `docs/arch/port_allocation.md`.
    *   `docs/services/api.md` (inputs and outputs), `services/controller/README.md`.
    *   `VISION.md` (the service table), `AGENTS.md` §5 (the Redis row), `.env.example` and `compose.yml` (`SILVASONIC_REDIS_*`, the `redis` service).
    *   The v1.0.0 milestone: the tasks that exist only "if ADR-0041 keeps Redis".
