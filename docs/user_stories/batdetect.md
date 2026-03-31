# User Stories — BatDetect Service

> **Service:** BatDetect · **Tier:** 2 (Immutable) · **Status:** Planned (since v1.3.0)

---

## US-BD01: Automatically detect bat species 🦇

> **As a researcher**
> **I want** my ultrasound recordings to be automatically analyzed for bat calls and the detected species to appear in the database with timestamp and confidence,
> **so that** I get a complete bat species inventory of my location — without having to manually search every recording in the spectrogram.

### Acceptance Criteria

- [ ] All indexed recordings with a sufficiently high sample rate are automatically analyzed — without manual triggering.
- [ ] For each detected bat call, the species, the time in the audio, and a confidence value are stored.
- [ ] The analysis uses the original recording (full hardware quality), not the downsampled standard version.
- [ ] Already analyzed recordings are not processed again.
- [ ] The model is trained or fine-tuned on **Central European bat species** (DACH region).

### Milestone

- **Milestone:** v1.3.0

### References

- [BatDetect Service Docs](../services/batdetect.md)
- [ADR-0018: Worker Pull Orchestration](../adr/0018-worker-pull-orchestration.md)
- [Recorder User Stories — US-R03: Original format and standard format simultaneously](./recorder.md)

---

## US-BD02: Analyze only ultrasound microphones 🎤

> **As a user**
> **I want** only recordings from microphones that can actually record ultrasound to be analyzed,
> **so that** no computing power is wasted on standard microphones (48 kHz) which contain no bat calls anyway.

### Acceptance Criteria

- [ ] BatDetect only processes recordings with a sample rate ≥ 192 kHz (configurable).
- [ ] Recordings from standard microphones (e.g. 48 kHz) are automatically skipped.
- [ ] The filter is based on the sample rate of the recorded file — no manual assignment necessary.
- [ ] In the dashboard, it is visible which microphones are qualified for bat analysis.

### Milestone

- **Milestone:** v1.3.0

### References

- [BatDetect Service Docs §Inputs](../services/batdetect.md)
- [Microphone Profiles](../arch/microphone_profiles.md)

---

## US-BD03: Analyze only during bat-active hours ⏰

> **As a researcher**
> **I want** the bat analysis to only run for recordings from the evening and night hours (e.g. 19:00–07:00),
> **so that** no computing power is wasted on daytime recordings where bats are not active.

### Acceptance Criteria

- [ ] A time window (start and end hour) is configurable via the web interface (default: 19:00–07:00).
- [ ] Recordings outside the time window are skipped during analysis.
- [ ] The time window can be disabled so that all recordings are analyzed (e.g., for special studies).
- [ ] Changes to the time window are automatically applied (service restart).

### Milestone

- **Milestone:** v1.3.0

### References

- [BatDetect Service Docs §Dynamic Configuration](../services/batdetect.md)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)

---

## US-BD04: Adjust detection accuracy 🎚️

> **As a researcher**
> **I want to** be able to adjust the confidence threshold for bat detection,
> **so that** I receive either more individual records (lower threshold) or fewer false alarms (higher threshold) depending on my needs.

### Acceptance Criteria

- [ ] The confidence threshold is adjustable via the web interface (default: 25%).
- [ ] Detections below the threshold are not displayed in the species list.
- [ ] Changes are automatically applied — the service restarts if necessary.
- [ ] The current threshold is visible in the dashboard.

### Milestone

- **Milestone:** v1.3.0

### References

- [BatDetect Service Docs §Dynamic Configuration](../services/batdetect.md)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)

---

## US-BD05: View detected bat species in the web interface 📋

> **As a user**
> **I want to** see a list of all detected bat species in the web interface — with frequency, last detection, and activity history,
> **so that** I quickly understand which bat species occur at my location and when they are active.

### Acceptance Criteria

- [ ] The web interface shows a species list with the number of detections, last detection time, and average confidence.
- [ ] Each species has a detail page with description, image, and temporal activity history.
- [ ] The list can be sorted by frequency, date, or confidence.
- [ ] Bat detections are clearly separated from bird detections (separate area in the web interface).

### Milestone

- **Milestone:** v1.3.0

### References

- [BatDetect Service Docs §Outputs](../services/batdetect.md)

---

> [!NOTE]
> **Recording Protection:** This service must not impair the ongoing recording. Resource limits, QoS prioritization, and file isolation are managed centrally by the Controller (→ [US-C04](./controller.md), [US-R02](./recorder.md)).

---

## US-BD06: Analysis status in dashboard 📊

> **As a user**
> **I want to** see in the dashboard how many recordings are still waiting for bat analysis and whether BatDetect is currently active,
> **so that** I can assess the state of the analysis pipeline at any time.

### Acceptance Criteria

- [ ] The dashboard shows: number of pending recordings, last analyzed file, and current activity (active/waiting/offline).
- [ ] In case of problems (e.g., BatDetect stopped or lagging), a warning is displayed.
- [ ] BatDetect reports its status periodically to the web interface.
- [ ] Resource consumption (RAM, CPU) is visible in the dashboard — to help decide whether BatDetect should remain activated.

### Milestone

- **Milestone:** v1.3.0

### References

- [ADR-0019: Unified Service Infrastructure §Heartbeat](../adr/0019-unified-service-infrastructure.md)
- [BatDetect Service Docs](../services/batdetect.md)

---

## US-BD07: Enable and disable BatDetect 🔌

> **As a user**
> **I want to** be able to enable or disable bat detection via the web interface,
> **so that** I save computing power and energy when I don't need the analysis or no ultrasound microphone is connected.

### Acceptance Criteria

- [ ] BatDetect is **disabled by default** — the user must consciously turn on the analysis.
- [ ] When enabled, the system checks if an ultrasound-capable microphone is connected and warns if not.
- [ ] When disabled, the service is cleanly terminated — no ongoing analysis is aborted.
- [ ] Upon reactivation, BatDetect autonomously processes the accumulated backlog.
- [ ] The current state (active/disabled) is visible in the dashboard.

### Milestone

- **Milestone:** v1.3.0

### References

- [Controller User Stories — US-C03: Control services via web interface](./controller.md)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)
