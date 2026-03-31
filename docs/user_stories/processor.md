# User Stories — Processor Service

> **Service:** Processor · **Tier:** 1 (Infrastructure, Immutable) · **Status:** Implemented (v0.5.0)

---

## US-P01: Recordings appear automatically in the overview 📋

> **As a field researcher**
> **I want** new audio recordings to automatically appear in my overview (web interface) as soon as they are recorded,
> **so that** I don't need a manual import step and the recordings are immediately visible and analyzable.

### Acceptance Criteria

- [x] New `.wav` files in the recording directory are detected within a few seconds (periodic scanning, see [Processor Service §5](../services/processor.md) for default value).
- [x] Metadata (duration, sample rate, channels, file size) is automatically extracted and written to the database.
- [x] Already registered recordings are not duplicated (idempotent).
- [x] Only completely written files are captured — incomplete buffer files are ignored.

### Non-Functional Requirements

- Scanning works **without Redis** — recording and indexing are in no case dependent on Redis (Critical Path).
- A Processor failure does **not** block the analysis of already captured recordings — analysis workers continue to operate independently.

### Milestone

- **Milestone:** v0.5.0

### References

- [Processor Service Docs §Indexer](../services/processor.md)
- [ADR-0018: Worker Pull Orchestration](../adr/0018-worker-pull-orchestration.md)
- [Messaging Patterns §Critical Path](../arch/messaging_patterns.md)
- [Recorder README §Buffer to Records](../../services/recorder/README.md)

---

## US-P02: Endless recording without storage worries 💾

> **As a field researcher**
> **I want** my device to record indefinitely without running out of storage,
> **so that** I can leave the station in the field unattended for weeks or months.

### Acceptance Criteria

- [x] Storage utilization is continuously monitored and automatically cleaned up if necessary:

| Level | Threshold | What gets deleted | Notice |
|---|---|---|---|
| **Cleanup** | > 70% | Recordings that are uploaded (to **all** active targets) AND completely analyzed | `INFO` |
| **Precaution** | > 80% | Recordings that are uploaded (to **all** active targets, independent of analysis status) | `WARNING` |
| **Emergency** | > 90% | **Oldest** recordings independent of status (even if not uploaded!) | `CRITICAL` |

- [x] Deleted files disappear from the hard drive, but remain in the inventory (database) as an entry — the recording history is not lost.
- [x] In emergency mode, cleanup also works during a database outage (fallback to file age).
- [x] Only the Processor may delete recording files — no other service has write access to the recording directory.
- [x] Deletions are logged traceably (filename, deletion reason, level).

### Non-Functional Requirements

- **Priority: Continue recording > Data archiving** — better to delete old data than to stop the current recording.
- Cleanup is the core reason why the Processor is classified as a critical infrastructure service.

### Milestone

- **Milestone:** v0.5.0

### References

- [Processor Service Docs §Janitor](../services/processor.md)
- [ADR-0011: Audio Recording Strategy §6 Retention Policy](../adr/0011-audio-recording-strategy.md)
- [ADR-0009: Zero-Trust Data Sharing](../adr/0009-zero-trust-data-sharing.md)

---

## US-P03: Adjust storage rules via web interface 🎛️

> **As a user**
> **I want** to adjust the storage cleanup rules (at what utilization cleanup begins) via the web interface,
> **so that** I can adapt the behavior to my location and storage capacity — without technical configuration files.

### Acceptance Criteria

- [x] Thresholds (Cleanup / Precaution / Emergency) and scan intervals can be changed in the settings.
- [x] (via Web-Mock) After a change, the service is automatically restarted and applies the new values.
- [x] Sensible default values are pre-assigned out-of-the-box (thresholds and intervals see [Processor Service §5](../services/processor.md)).

### Milestone

- **Milestone:** v0.5.0 (Backend: Config Seeding) + v0.8.0 (Frontend: Web-Interface)

### References

- [ADR-0019: Unified Service Infrastructure](../adr/0019-unified-service-infrastructure.md)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)

---

## US-P04: Data pipeline status in dashboard 📊

> **As a user**
> **I want** to see at a glance in the dashboard whether my data pipeline is running — how many recordings are not yet captured, in what mode the storage cleanup is operating, and how full my storage is,
> **so that** I can assess the state of my station at any time.

### Acceptance Criteria

- [x] (via Web-Mock) The web interface displays the current data pipeline status (e.g., last capture, open backlog, storage utilization, current cleanup level).
- [x] (via Web-Mock) The status updates in real-time as long as the station is reachable.
- [x] If the status transmission fails, the data pipeline still continues without disruption.

### Milestone

- **Milestone:** v0.5.0 (Backend: Heartbeat Payload) + v0.8.0 (Frontend: Dashboard)

### References

- [ADR-0019: Unified Service Infrastructure §Heartbeat](../adr/0019-unified-service-infrastructure.md)
- [Messaging Patterns §Heartbeat Payload](../arch/messaging_patterns.md)
- [Web-Interface §Processor](../services/web_interface.md)
