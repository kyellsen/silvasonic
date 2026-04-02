# User Stories — Upload / Cloud Sync (Archived)

> **Service:** ~~Uploader~~ → Processor Cloud-Sync-Worker · ~~**Tier:** 2~~ → Tier 1 (Processor) · **Status:** Archived — migrated to Processor (v0.6.0)
>
> [!WARNING]
> **Archived:** The standalone Uploader service has been replaced by an internal Cloud-Sync-Worker within the Processor. User stories below are retained for traceability but reflect the original multi-target architecture. The KISS refactoring simplifies to a single-target model. See [Refactoring Plan](../development/refactoring_uploader_to_processor.md).

---

<a id="us-u01"></a>
## US-U01: Automatically back up recordings to the cloud ☁️

> **As a researcher**
> **I want** my recordings to be automatically uploaded to a remote storage (e.g., Nextcloud, S3),
> **so that** my data is safe even in case of device loss, theft, or hardware failure.

### Acceptance Criteria

- [ ] New recordings are automatically detected and uploaded to the cloud — without manual intervention.
- [ ] Before upload, files are losslessly compressed (FLAC) to save bandwidth (~50% smaller).
- [ ] After confirmed upload to the configured remote target, the file is marked as "uploaded" in the database (`uploaded=true`).
- [ ] The device also works without an internet connection — recordings are stored locally and caught up upon connection (Store & Forward).

### Milestone

- **Milestone:** v0.6.0

### References

- [Uploader Service Docs](../services/uploader.md)
- [ADR-0011: Audio Recording Strategy](../adr/0011-audio-recording-strategy.md)
- [ADR-0009: Zero-Trust Data Sharing](../adr/0009-zero-trust-data-sharing.md)

---

<a id="us-u02"></a>
## US-U02: Record indefinitely ♾️

> **As a user**
> **I want to** ensure that uploaded recordings may be automatically deleted from local storage,
> **so that** the station can record continuously for months or years without manual intervention.

### Acceptance Criteria

- [ ] After confirmed upload to the configured remote target, the system marks the file as backed up (`uploaded=true`).
- [ ] The storage cleanup service (Janitor) may only delete files marked as "uploaded" (→ US-P02).
- [ ] The interaction of upload and cleanup permanently keeps local storage below critical thresholds.
- [ ] In case of a permanent lack of internet connection, the Janitor still intervenes — recording always takes precedence over archiving.

### Milestone

- **Milestone:** v0.6.0

### References

- [Uploader Service Docs §Outputs](../services/uploader.md)
- [Processor User Stories — US-P02: Endless recording without storage worries](./processor.md)
- [ADR-0011 §Retention Policy](../adr/0011-audio-recording-strategy.md)

---

<a id="us-u03"></a>
## ~~US-U03: Multiple storage targets simultaneously 🗄️~~ (Archived)

> **Archived:** The KISS refactoring replaces the multi-target Uploader with a single-target Cloud-Sync-Worker within the Processor. This user story is no longer applicable.

### References

- [Refactoring Plan](../development/refactoring_uploader_to_processor.md)

---

<a id="us-u04"></a>
## US-U04: Adjust upload settings via web interface 🎛️

> **As a user**
> **I want to** be able to change upload settings (bandwidth, time window, storage targets) via the web interface,
> **so that** I adjust the upload to my network situation and needs — without SSH or config files.

### Acceptance Criteria

- [ ] Bandwidth limit is adjustable (e.g., "max 1 MB/s") to avoid overloading the internet connection.
- [ ] A time window for uploads can be defined (e.g., only at night from 22:00–06:00) to save bandwidth during the day.
- [ ] New storage targets can be added, edited, and removed via the web interface.
- [ ] Changes are automatically applied — the upload service restarts if necessary.

### Milestone

- **Milestone:** v0.6.0 (Backend: UploaderSettings Schema, Schedule, Bandwidth Limit) + v0.9.0 (Frontend: Web Interface)

### References

- [Uploader Service Docs §Dynamic Configuration](../services/uploader.md)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)

---

<a id="us-u05"></a>
## US-U05: Upload progress and status in dashboard 📊

> **As a user**
> **I want to** see in the dashboard how many recordings still need to be uploaded and whether there are problems,
> **so that** I can assess the cloud sync state of my station at any time.

### Acceptance Criteria

- [ ] The dashboard shows: number of pending uploads, current upload speed, and last successful upload time.
- [ ] A warning is shown for failed uploads (e.g., "Connection to Nextcloud failed for 2 hours").
- [ ] Status can be viewed individually per storage target.
- [ ] The upload service reports its status periodically to the web interface.

### Milestone

- **Milestone:** v0.6.0 (Backend: Heartbeat Payload) + v0.9.0 (Frontend: Dashboard)

### References

- [ADR-0019: Unified Service Infrastructure §Heartbeat](../adr/0019-unified-service-infrastructure.md)
- [Uploader Service Docs](../services/uploader.md)

---

<a id="us-u06"></a>
## US-U06: Seamless upload tracking 📋

> **As a researcher**
> **I want to** be able to trace at any time which recordings were uploaded when and where,
> **so that** I am certain no data was lost on the way.

### Acceptance Criteria

- [ ] Every upload attempt is logged — success, failure, file size, duration, and target.
- [ ] The upload log is viewable via the web interface.
- [ ] Failed uploads are automatically retried.
- [ ] Persistently failed uploads are shown as a warning in the dashboard (→ US-U05).

### Milestone

- **Milestone:** v0.6.0

### References

- [Uploader Service Docs §Audit Logging](../services/uploader.md)

---

> [!NOTE]
> **Recording Protection:** This service must not impair the ongoing recording. Resource limits, QoS prioritization, and file isolation are managed centrally by the Controller (→ [US-C04](./controller.md), [US-R02](./recorder.md)).
