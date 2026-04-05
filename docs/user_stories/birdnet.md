# User Stories — BirdNET Service

> **Service:** BirdNET · **Tier:** 2 (Immutable)

---

<a id="us-b01"></a>
## US-B01: Automatically detect bird species 🐦

> **As a researcher**
> **I want** my recordings to be automatically analyzed for bird calls and the detected species to appear in the database with timestamp and confidence,
> **so that** I get a complete species inventory of my location — without having to manually listen to every recording.

### Acceptance Criteria

- [ ] All indexed recordings are automatically analyzed — without manual triggering.
- [ ] For each detected bird call, the species, the time in the audio, and a confidence value are stored.
- [ ] For each detection, a short audio clip (WAV) is extracted and saved to the BirdNET workspace. The file path is stored in the database.
- [ ] The length of the extracted clip (pre- and post-roll padding) is globally configurable.
- [ ] The analysis runs in the background and processes the backlog autonomously.
- [ ] Already analyzed recordings are not processed again.

### References

- [BirdNET Service Docs](../services/birdnet.md)
- [ADR-0018: Worker Pull Orchestration](../adr/0018-worker-pull-orchestration.md)

---

<a id="us-b02"></a>
## US-B02: View detected species in the web interface 📋

> **As a user**
> **I want to** see a list of all detected bird species in the web interface — with frequency, last detection, and confidence,
> **so that** I quickly understand which species occur at my location.

### Acceptance Criteria

- [ ] The web interface shows a species list with the number of detections, last detection time, and average confidence.
- [ ] Each species has a detail page with description, image, and temporal activity history.
- [ ] The list can be sorted by frequency, date, or confidence.
- [ ] Only detections above the configured confidence threshold are displayed.
- [ ] Each detection has a playable audio clip in the detail view (Wavesurfer.js player with spectrogram overlay).

### References

- [BirdNET Service Docs §Outputs](../services/birdnet.md)

---

<a id="us-b03"></a>
## US-B03: Adapt detection to location and season 📍📅

> **As a researcher**
> **I want to** be able to enter the location of my station (latitude, longitude),
> **so that** the bird species detection is restricted to regionally and seasonally occurring species (using the recording's date), yielding fewer false positives.

### Acceptance Criteria

- [ ] Location coordinates are configurable in the system settings (web interface).
- [ ] BirdNET uses the coordinates and the week of the year (derived automatically from the recording timestamp) to restrict the species model to the region and season.
- [ ] Changes to the coordinates are applied automatically (service is restarted if necessary).
- [ ] The default location is sensibly prefilled.

### References

- [BirdNET Service Docs §Dynamic Configuration](../services/birdnet.md)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)
- [Controller User Stories — US-C08: Works immediately after installation](./controller.md)

---

<a id="us-b04"></a>
## US-B04: Adjust detection accuracy 🎚️

> **As a researcher**
> **I want to** be able to adjust the confidence threshold, sensitivity, and overlap for bird species detection,
> **so that** I receive either more individual records (e.g., lower threshold, higher sensitivity) or fewer false alarms depending on my needs.

### Acceptance Criteria

- [ ] The confidence threshold, sensitivity, and overlap parameters are adjustable via the web interface.
- [ ] Detections below the confidence threshold are ignored.
- [ ] Changes are automatically applied — the service restarts if necessary.
- [ ] The current threshold and configuration are visible in the dashboard.

### References

- [BirdNET Service Docs §Dynamic Configuration](../services/birdnet.md)
- [ADR-0023: Configuration Management](../adr/0023-configuration-management.md)

---

> [!NOTE]
> **Recording Protection:** This service must not impair the ongoing recording. Resource limits, QoS prioritization, and file isolation are managed centrally by the Controller (→ [US-C04](./controller.md), [US-R02](./recorder.md)).

> [!NOTE]
> **Data Retention:** Handling the deletion of BirdNET clips when the original recording is purged by the Processor's Janitor is explicitly deferred to a future follow-up issue rather than being automatically handled in v0.8.0.

---

<a id="us-b05"></a>
## US-B05: Analysis status in dashboard 📊

> **As a user**
> **I want to** see in the dashboard how many recordings are still waiting for analysis and whether BirdNET is currently active,
> **so that** I can assess the state of the analysis pipeline at any time.

### Acceptance Criteria

- [ ] The dashboard shows: number of pending recordings, last analyzed file, and current activity (active/waiting/offline).
- [ ] In case of problems (e.g., BirdNET stopped or lagging), a warning is displayed.
- [ ] BirdNET reports its status periodically to the web interface.

### References

- [ADR-0019: Unified Service Infrastructure §Heartbeat](../adr/0019-unified-service-infrastructure.md)
- [BirdNET Service Docs](../services/birdnet.md)

---

<a id="us-b06"></a>
## US-B06: Enable and disable BirdNET 🔌

> **As a user**
> **I want to** be able to enable or disable bird species detection via the web interface,
> **so that** I save computing power and energy when I don't need the analysis.

### Acceptance Criteria

- [ ] BirdNET can be enabled and disabled via the web interface.
- [ ] When disabled, the service is cleanly terminated — no ongoing analysis is aborted.
- [ ] Upon reactivation, BirdNET autonomously processes the accumulated backlog.
- [ ] The current state (active/disabled) is visible in the dashboard.

### References

- [Controller User Stories — US-C03: Control services via web interface](./controller.md)
- [ADR-0017: Service State Management](../adr/0017-service-state-management.md)

---

<a id="us-b07"></a>
## US-B07: Prioritize analysis backlog order 🔀

> **As a user or researcher**
> **I want to** be able to define via the web interface whether BirdNET should process the oldest or the newest recordings in the backlog first,
> **so that** I can prioritize either a continuous chronological analysis (oldest first) or receive immediate live results of the most recent captures (newest first).

### Acceptance Criteria

- [ ] The processing order ("Oldest first" vs "Newest first") is adjustable via the web interface.
- [ ] This setting is technically modeled as a literal field (`processing_order: Literal["oldest_first", "newest_first"] = "oldest_first"`) in the `BirdnetSettings` Pydantic schema, ensuring the web interface can automatically render a dropdown.
- [ ] The BirdNET worker dynamically alters its database pull query (`ORDER BY time ASC` vs `DESC`) based on the active setting.
- [ ] Changes to the processing order are applied immediately or upon the next worker cycle.

