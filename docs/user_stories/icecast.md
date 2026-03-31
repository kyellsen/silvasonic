# User Stories — Icecast Service

> **Service:** Icecast · **Tier:** 1 (Infrastructure) · **Status:** Planned (since v1.1.0)

---

## US-IC01: Listen live via browser 🔊

> **As a user**
> **I want to** listen to the live audio of my station directly in the browser,
> **so that** I can check locally or remotely if the microphones are working correctly — without having to download files.

### Acceptance Criteria

- [ ] The live audio stream can be started and stopped by clicking in the web interface.
- [ ] Playback starts within a few seconds — no minutes of buffering.
- [ ] The stream only consumes resources when someone is actually listening.
- [ ] The stream is usable even over a mobile connection (e.g. Tailscale).

### Milestone

- **Milestone:** v1.1.0

### References

- [Icecast Service Docs](../services/icecast.md)
- [ADR-0011: Audio Recording Strategy §5 Live Opus Stream](../adr/0011-audio-recording-strategy.md)
- [Recorder User Stories — US-R04: Listen live via browser](./recorder.md)
- [Gateway User Stories — US-GW01: Everything accessible via one address](./gateway.md)

---

## US-IC02: Select microphone for listening 🎤

> **As a user**
> **I want to** be able to select which of my connected microphones I want to listen to live,
> **so that** I can specifically check individual locations or frequency ranges.

### Acceptance Criteria

- [ ] The web interface displays a list of all currently active microphones.
- [ ] You can switch between microphones by clicking — without having to reload the page.
- [ ] If a microphone is disconnected, it disappears from the selection; if reconnected, it appears automatically.

### Milestone

- **Milestone:** v1.1.0

### References

- [Icecast Service Docs §Mount Point Management](../services/icecast.md)
- [Recorder User Stories — US-R05: Multiple microphones simultaneously](./recorder.md)
- [Controller User Stories — US-C01: Plug in microphone — immediately recognized](./controller.md)

---

## US-IC03: Share audio stream externally 🌍

> **As a researcher**
> **I want to** be able to share the live audio stream of my station as a URL,
> **so that** colleagues, students, or citizen science participants can follow the soundscape in real-time — without needing access to the web interface.

### Acceptance Criteria

- [ ] Each microphone has its own stable stream URL.
- [ ] The URL can be opened in any common audio player (VLC, browser).
- [ ] External access can be disabled or password-protected if necessary.
- [ ] The number of simultaneous listeners is limited so as to not overload the station.

### Milestone

- **Milestone:** v1.1.0

### References

- [Icecast Service Docs §Outputs](../services/icecast.md)
- [Gateway User Stories — US-GW03: Station is protected against unauthorized access](./gateway.md)

---

> [!NOTE]
> **Recording Protection:** The live stream is best-effort — a failure of the streaming server does not impact ongoing file recording. Resource limits and prioritization are managed centrally by the Controller (→ [US-C04](./controller.md), [US-R02](./recorder.md), [ADR-0011 §5](../adr/0011-audio-recording-strategy.md)).
