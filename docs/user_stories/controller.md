# User Stories — Controller Service

> **Service:** Controller · **Tier:** 1 (Infrastructure) · **Status:** Implemented (since v0.3.0)

---

<a id="us-c01"></a>
## US-C01: Plug in microphone — immediately recognized 🎙️⚡

> **As a user** I want to plug in a USB microphone and see a system reaction within a maximum of 1 second,
> **so that** I don't need technical knowledge, capture data immediately, and a disconnected microphone is handled cleanly.

### Acceptance Criteria

#### Hardware Detection
- [x] **All** USB audio devices on the host are recognized — not just those with a known profile.
- [x] Stable USB identification (Vendor-ID, Product-ID, Serial) is done via direct `sysfs` reading (`pathlib`) — no external dependencies.
- [x] ALSA cards are correlated via `/proc/asound/cards` to determine the ALSA device name (e.g. `hw:2,0`).

#### Plugging In & Removal
- [x] **Reaction time ≤ 1 second** — the reconciliation loop polls for changes every 1 second.
- [x] A newly detected microphone is automatically created in the device list as `pending` / `status=online`.
- [x] Temporary removal of a microphone (USB Flapping) is bridged via a grace period. A longer disconnect sets `status=offline` and cleanly stops the associated recording.

#### Stable Re-recognition
- [x] A re-plugged microphone is recognized by its stable device ID (Vendor-ID + Product-ID + Serial, or Port-Fallback).
- [x] No duplicate device entry is created — the existing recorder with its workspace and identity is reactivated.

#### Profile Assignment
- [x] When a new device is detected, it is automatically checked if a matching microphone profile exists.
- [x] On exact match: automatic assignment.
- [x] On no or ambiguous match: device remains pending — user selects profile in the Web-Interface.
- [x] The correct profile is automatically provided to the recording instance.

### Non-Functional Requirements

- Detection must work on **all common Linux distributions** and in rootless Podman containers.
- Polling runs as part of the reconciliation loop and must not block other Controller functions.

### Milestone

- **Milestone:** v0.3.0

### References

- [Controller README §Device State Evaluation](https://github.com/kyellsen/silvasonic/blob/main/services/controller/README.md)
- [ADR-0013: Tier 2 Container Management](../adr/0013-tier2-container-management.md)
- [ADR-0016: Hybrid YAML/DB Profiles](../adr/0016-hybrid-yaml-db-profiles.md)

---

<a id="us-c02"></a>
## US-C02: Crashed services restart automatically 🛡️

> **As a user** I want crashed recording services to automatically restart,
> **so that** recording never stops unnoticed.

### Acceptance Criteria

- [x] The regular reconciliation cycle detects missing or crashed services and restarts them.
- [x] Container restart policy (`on-failure`, max 5) as the first fast fallback.
- [x] On Controller restart, existing recording instances are adopted (not restarted).
- [x] On Controller crash, recording instances continue running undisturbed.
- [x] **Priority: Data capture > clean shutdown.**

### Milestone

- **Milestone:** v0.3.0

### References

- [Controller README §Reconciliation Loop](https://github.com/kyellsen/silvasonic/blob/main/services/controller/README.md)
- [Controller README §Shutdown Semantics](https://github.com/kyellsen/silvasonic/blob/main/services/controller/README.md)
- [ADR-0013 §Restart Policy](../adr/0013-tier2-container-management.md)

---

<a id="us-c03"></a>
## US-C03: Control services via web interface 🎛️

> **As a user** I want to enable or disable services (e.g., BirdNET, Weather) via the web interface,
> **so that** I can save resources without having to use SSH.

### Acceptance Criteria

- [x] The Controller reacts to change signals and immediately reads the desired state from the database.
- [x] Desired state from `system_services` and `devices` is correctly evaluated.
- [x] Services are started or stopped based on the `enabled` flag.
- [x] On configuration change: stop service and restart with new settings.
- [x] If a signal is lost (e.g., Controller restart), the reconciliation timer catches the change as a fallback.

### Milestone

- **Milestone:** v0.3.0

### References

- [Controller README §Reconcile-Nudge Subscriber](https://github.com/kyellsen/silvasonic/blob/main/services/controller/README.md)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)
- [Messaging Patterns §State Reconciliation](../arch/messaging_patterns.md)

---

<a id="us-c04"></a>
## US-C04: Recording always takes priority ⚡

> **As a user** I want to be certain that recording never aborts due to lack of memory or overloaded analysis/upload services,
> **so that** no data is lost — regardless of which services run concurrently.

### Acceptance Criteria

#### Resource Management
- [x] Every service container receives memory and CPU limits upon creation.
- [x] No service may be started without resource limits.
- [x] The Controller statically applies limits globally upon container creation — individual services don't have to limit themselves.

#### QoS Prioritization
- [x] Recording instances are maximally protected (lowest OOM score) — they are the last to be terminated by the system.
- [x] Analysis services (BirdNET, BatDetect) are marked as "expendable" and are terminated **first** during bottlenecks.
- [x] Upload and infrastructure services (Processor Cloud-Sync-Worker, Gateway) also receive lower priority than recording.

#### File Isolation (Zero-Trust)
- [x] All non-recording services receive **read-only** access to recording files (Read-Only Bind Mounts).
- [x] Only the Processor may delete recording files — no other service has write access to the recording directory.

### Non-Functional Requirements

- **Priority: Data capture > Analysis > Upload > Web Access** — this order determines which services are terminated first during resource scarcity.

### Milestone

- **Milestone:** v0.3.0

### References

- [Controller README §Resource Limits & QoS](https://github.com/kyellsen/silvasonic/blob/main/services/controller/README.md)
- [ADR-0020: Resource Limits & QoS](../adr/0020-resource-limits-qos.md)
- [ADR-0009: Zero-Trust Data Sharing](../adr/0009-zero-trust-data-sharing.md)
- [Recorder User Stories — US-R02: Recording always continues](recorder.md)

---

<a id="us-c05"></a>
## US-C05: System status in dashboard 📊

> **As a user** I want to see the overall utilization of my station (CPU, RAM, storage) in the dashboard,
> **so that** I can assess its condition at any time.

### Acceptance Criteria

- [x] The Controller collects system-wide metrics (CPU, RAM, storage).
- [ ] Metrics are periodically transmitted to the web interface.
- [ ] The web interface displays both individual service and overall system metrics.

### Milestone

- **Milestone:** v0.2.0 (Data Collection) + v0.9.0 (Dashboard Display)

### References

- [Controller README §Redis: Heartbeat + Status Aggregator](https://github.com/kyellsen/silvasonic/blob/main/services/controller/README.md)
- [ADR-0019 §2.4: Heartbeat Payload Schema](../adr/0019-unified-service-infrastructure.md)

---

<a id="us-c06"></a>
## US-C06: Manage microphone profiles 🔧

> **As a user** I want predefined microphone profiles to be automatically available
> and new profiles to be creatable via the web interface,
> **so that** different microphone hardware is supported.

### Acceptance Criteria

- [x] On startup: bundled standard profiles are automatically loaded.
- [x] During the seed process, each profile is checked: does a user profile with the same name exist? → Yes: skip. No: load system profile.
- [x] User profiles are therefore never overwritten.
- [x] Profile data is validated against the `MicrophoneProfile` Pydantic schema before being saved.

### Milestone

- **Milestone:** v0.3.0

### References

- [Controller README §Profile Injection](https://github.com/kyellsen/silvasonic/blob/main/services/controller/README.md)
- [ADR-0016: Hybrid YAML/DB Profile Management](../adr/0016-hybrid-yaml-db-profiles.md)
- [Microphone Profiles](../arch/microphone_profiles.md)

---

<a id="us-c07"></a>
## US-C07: Disable microphone immediately ⛔

> **As a user** I want to be able to disable a microphone immediately (e.g., in case of malfunction),
> **so that** the system remains under control without a reboot.

### Acceptance Criteria

- [x] `enabled=false` at the device level → immediate recording shutdown.
- [x] The halt occurs independently of the assignment status.
- [x] Change signal ensures immediate reaction; the reconciliation timer acts as a fallback.
- [x] Recording is cleanly terminated (no hard kill).

### Milestone

- **Milestone:** v0.3.0

### References

- [Controller README §Enrollment State Machine](https://github.com/kyellsen/silvasonic/blob/main/services/controller/README.md)

---

<a id="us-c08"></a>
## US-C08: Works immediately after installation 🏭

> **As a user** I want all sensible default values to be loaded after a fresh install,
> **so that** the system is immediately ready for operation.

### Acceptance Criteria

- [x] Standard configuration is loaded on startup (only if not already present).
- [x] Standard microphone profiles are loaded and updated from YAML seed files (ADR-0016).
- [x] A default admin account is created on startup if none exists (ADR-0023 §2.4). Password is hashed with bcrypt.
- [x] Already changed values and user-created profiles are never overwritten.
- [x] After a database reset, all defaults are automatically restored on the next startup.

> **Note:** The default password must be changed in production via the web interface.

### Milestone

- **Milestone:** v0.3.0

### References

- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)

---

<a id="us-c09"></a>
## US-C09: Live service logs in browser 📜

> **As a user** I want to see the logs of all services live in the web interface,
> **so that** I can rapidly diagnose issues.

### Acceptance Criteria

- [x] The Controller reads the logs of all managed services.
- [ ] Logs are forwarded in real-time to the web interface.
- [x] With no active viewers, logs are simply discarded (no resource consumption).
- [ ] The web interface displays logs with auto-scroll.

### Milestone

- **Milestone:** v0.3.0 (Controller Log Forwarder) + v0.9.0 (Web Display)

### References

- [ADR-0022: Live Log Streaming](../adr/0022-live-log-streaming.md)
- [ADR-0013 §Logging](../adr/0013-tier2-container-management.md)

---

<a id="us-c10"></a>
## US-C10: Unknown microphone works immediately 🎤

> **As a user** I want to plug in any USB microphone and record right away,
> **so that** I need no prior configuration and the system is instantly useful even with unknown hardware.

### Acceptance Criteria

#### Auto-Fallback Profile
- [x] A `generic_usb` system profile is seeded on startup (48 kHz, 1 ch, S16LE, Gain 0 dB).
- [x] If no profile match (score 0) is found, the Controller automatically assigns `generic_usb`.
- [x] The device receives `enrollment_status=enrolled` and `profile_slug=generic_usb`.
- [x] The recorder starts immediately with standard settings.

#### Upgrade Path
- [ ] ~~The user can assign a better profile or create a custom one via the web interface~~ (v0.9.0+).
- [ ] ~~On profile change, the recorder is automatically restarted with the new configuration~~ (v0.9.0+).

### Non-Functional Requirements

- The Generic profile must work with **every** USB audio device (conservative settings).
- **Priority: Start recording > optimal quality** — better to record at 48 kHz than not at all.

### Milestone

- **Milestone:** v0.4.0

### References

- [ADR-0016: Hybrid YAML/DB Profile Management](../adr/0016-hybrid-yaml-db-profiles.md)
- [Microphone Profiles §Matching Algorithm](../arch/microphone_profiles.md)
- [Milestone v0.4.0](../development/milestone_0_4_0.md)
