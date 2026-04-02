# User Stories — Recorder Service

> **Service:** Recorder · **Tier:** 2 (Immutable)

---

<a id="us-r01"></a>
## US-R01: Plug in microphone — recording starts 🎙️

> **As a field researcher**
> **I want to** plug in a USB microphone and have the recording start automatically with the correct settings,
> **so that** I don't need technical knowledge for commissioning.

### Acceptance Criteria

- [x] Microphone is recognized within a few seconds — goal is a near real-time feel, not 10-second polling.
- [x] Matching microphone profile (sample rate, channels, gain) is automatically assigned — if needed, the user can adjust in the web interface.
- [x] A dedicated recording instance is started with the correct profile settings.
- [x] No manual configuration required — neither config files nor environment variables.

### References

- [Controller README §Device State Evaluation](https://github.com/kyellsen/silvasonic/blob/main/services/controller/README.md)
- [ADR-0013: Tier 2 Container Management](../adr/0013-tier2-container-management.md)
- [ADR-0016: Hybrid YAML/DB Profiles](../adr/0016-hybrid-yaml-db-profiles.md)
- [Microphone Profiles](../arch/microphone_profiles.md)

---

<a id="us-r02"></a>
## US-R02: Recording always continues 🛡️

> **As a researcher**
> **I want** the audio recording to continue under all circumstances — not interrupted by storage shortages, network outages, restarts of other services, nor by ongoing analysis or uploads,
> **so that** no scientific data is lost.

### Acceptance Criteria

#### Recording Robustness
- [x] The recording service is the last to be terminated by the system — in case of memory shortage, analysis services are stopped first.
- [x] A failure of status transmission (Redis) does not stop the recording.
- [x] A failure of the Controller → recording continues undisturbed.
- [x] On errors in the recording pipeline, an automatic restart occurs.

#### Isolation from other services
- [x] No other service (BirdNET, BatDetect) may impact the recording (Enforced by Controller cgroups).
- [x] All non-recording services receive CPU and memory limits (Enforced by Controller).
- [x] Analysis and upload services access recording files **read-only** (Enforced by Zero-Trust mounts).
- [x] The crash of any analysis or upload service has no impact.

### Non-Functional Requirements

- **Priority: Data capture > everything else** — in doubt, analysis, upload or web access will be terminated, never the recording.

### References

- [ADR-0020: Resource Limits & QoS](../adr/0020-resource-limits-qos.md)
- [ADR-0019: Unified Service Infrastructure](../adr/0019-unified-service-infrastructure.md)
- [ADR-0009: Zero-Trust Data Sharing](../adr/0009-zero-trust-data-sharing.md)
- [Recorder README](https://github.com/kyellsen/silvasonic/blob/main/services/recorder/README.md)
- [Controller User Stories — US-C04: Recording always takes priority](./controller.md)

---

<a id="us-r03"></a>
## US-R03: Original format and standard format simultaneously 🎧

> **As a researcher**
> **I want to** simultaneously obtain an unmodified original recording (full hardware quality) and a standardized version (48 kHz, 16-bit),
> **so that** I have the full spectrum for scientific analysis and ML services (BirdNET, BatDetect) receive a uniform format.

### Acceptance Criteria

- [x] Original recording: hardware-native sample rate and bit depth → `recorder/{name}/data/raw/*.wav`.
- [x] Standard recording: 48 kHz, 16-bit → `recorder/{name}/data/processed/*.wav`.
- [x] Both streams are written simultaneously without mutual interference.
- [x] Incomplete segments remain in `.buffer/` — only fully written files appear in `data/`.

### References

- [ADR-0011: Audio Recording Strategy](../adr/0011-audio-recording-strategy.md)
- [Recorder README](https://github.com/kyellsen/silvasonic/blob/main/services/recorder/README.md)

---

<a id="us-r04"></a>
## US-R04: Listen live via browser 🔊

> **As a user**
> **I want to** be able to listen to the microphone in real-time via the web interface,
> **so that** I can check locally or remotely if the station is recording correctly — without affecting the scientific recording.

### Acceptance Criteria

- [ ] A third audio stream is sent in low bitrate (Opus, 64 kbps) to the streaming server.
- [ ] A failure of the streaming server has no impact on file recording (Original + Standard).
- [ ] In the web interface, the desired microphone can be selected for listening.

### References

- [Icecast Service](../services/icecast.md)
- [Recorder README](https://github.com/kyellsen/silvasonic/blob/main/services/recorder/README.md)

---

<a id="us-r05"></a>
## US-R05: Multiple microphones simultaneously 🎤🎤

> **As a researcher**
> **I want to** be able to operate multiple USB microphones simultaneously,
> **so that** I can capture different frequency ranges or locations in parallel.

### Acceptance Criteria

- [x] One dedicated, independent recording instance runs per microphone.
- [x] Each instance has its own workspace on the hard drive (`recorder/{name}/`).

> [!NOTE]
> Individual activation/deactivation of microphones is a **Controller feature** (via database / web interface) and is documented there.

### References

- [ADR-0013: Tier 2 Container Management](../adr/0013-tier2-container-management.md)
- [Controller README §Container Labels](https://github.com/kyellsen/silvasonic/blob/main/services/controller/README.md)

---

<a id="us-r06"></a>
## US-R06: Automatic recovery on errors 🔄

> **As a user**
> **I want** a crashed or hanging recording to be restarted automatically,
> **so that** the station continues working without my intervention even with sporadic hardware faults.

### Acceptance Criteria

- [x] The recording pipeline is automatically restarted on detected errors (crash, hang, process death).
- [x] Multiple safeguard levels: internal watchdog → container restart → controller check (reconciliation interval).
- [x] Failed starts are limited (max. 5 retries) to avoid infinite loops.

### References

- [ADR-0013: Tier 2 Container Management](../adr/0013-tier2-container-management.md)
- [Recorder README](https://github.com/kyellsen/silvasonic/blob/main/services/recorder/README.md)

---

<a id="us-r07"></a>
## US-R07: Adjust recording duration per segment ⏱️

> **As a researcher**
> **I want to** be able to adjust the length of the recording segments via the microphone profile,
> **so that** I can adapt the file size and processing frequency to my use case.

### Acceptance Criteria

- [x] The segment duration is read from the microphone profile (default: 10 seconds).
- [ ] ~~The segment duration can be changed in the web interface~~ (🔮 Future)
- [x] Changes only take effect upon the next start of the recording instance.

### References

- [ADR-0016: Hybrid YAML/DB Profiles](../adr/0016-hybrid-yaml-db-profiles.md)
- [Microphone Profiles](../arch/microphone_profiles.md)
