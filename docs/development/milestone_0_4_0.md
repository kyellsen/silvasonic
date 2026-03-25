# Milestone v0.4.0 — Audio Recording (Dual Stream)

> **Target:** v0.4.0 — Recorder captures audio from USB microphones: FFmpeg Engine (ADR-0024), segmented WAV output, Profile Injection, Generic USB Fallback, Dual Stream (Raw + Processed), Watchdog & Auto-Recovery
>
> **Status:** 🔨 In Progress
>
> **References:** [ADR-0011](../adr/0011-audio-recording-strategy.md), [ADR-0013](../adr/0013-tier2-container-management.md), [ADR-0016](../adr/0016-hybrid-yaml-db-profiles.md), [ADR-0020](../adr/0020-resource-limits-qos.md), [ADR-0024](../adr/0024-ffmpeg-audio-engine.md), [Recorder README](../../services/recorder/README.md)
>
> **User Stories:** [US-R01](../user_stories/recorder.md#us-r01), [US-R02](../user_stories/recorder.md#us-r02), [US-R03](../user_stories/recorder.md#us-r03), [US-R06](../user_stories/recorder.md#us-r06), [US-R07](../user_stories/recorder.md#us-r07), [US-C10](../user_stories/controller.md#us-c10)

---

## Phase 1: Audio Pipeline & Single-Stream Capture

**Goal:** Recorder captures audio from an ALSA device using `ffmpeg` and writes segmented WAV files.

**User Stories:** US-R01 (Aufnahme)

### Tasks

- [x] Add `ffmpeg` as a system dependency in Recorder `Containerfile`
- [x] Remove legacy Python audio dependencies (`sounddevice`, `soxr`, `soundfile`) from `pyproject.toml` (ADR-0024)
- [x] Create `silvasonic/recorder/ffmpeg_pipeline.py` — Audio pipeline builder
  - Use `subprocess` to manage the FFmpeg execution
  - Input: ALSA device (e.g., `hw:1,0`) or Mock Source
  - Output: segmented WAV files in `.buffer/raw/` via FFmpeg segment muxer
  - Segment naming convention: `{ISO-timestamp}_{duration}s.wav`
- [x] Implement `.buffer/` → `data/` file promotion logic
  - On segment close: `SegmentPromoter` atomically moves from `.buffer/raw/` to `data/raw/`
  - Ensures Processor only sees complete files
- [x] Create workspace directory structure on startup:
  ```
  /app/workspace/           # bind-mount: instance-specific directory on host
  ├── data/raw/
  ├── data/processed/
  ├── .buffer/raw/
  └── .buffer/processed/
  ```
  > The Controller mounts **only** the instance-specific subdirectory into the
  > container (e.g. `workspace/recorder/{workspace_dir}:/app/workspace:z`).
  > The Recorder never sees the parent `recorder/` directory (ADR-0009, US-R02).
- [x] Read `SILVASONIC_RECORDER_DEVICE` from environment (ALSA device ID, e.g. `hw:1,0`)
  - `SILVASONIC_INSTANCE_ID` is also available (injected by Controller since v0.3.0, used for SilvaService heartbeats)
- [x] Unit tests: pipeline construction, segment naming, buffer-to-data promotion
- [x] Integration test: start Recorder with mock audio device, verify WAV files appear

---

## Phase 2: Profile Injection (Controller → Recorder)

**Goal:** Controller serializes the microphone profile and injects it into the Recorder via environment variable. Recorder parses the profile and applies all capture parameters.

**User Stories:** US-R01 (Profil-Settings), US-R07 (Segment-Dauer)

### Tasks

- [x] Parse `SILVASONIC_RECORDER_CONFIG_JSON` into the existing `MicrophoneProfile` Pydantic model (`silvasonic.core.schemas.devices`) at startup
  - The Controller serializes the `config` JSONB column from the `microphone_profiles` table and passes it as a single environment variable (ADR-0016)
  - The Recorder has **no database access** and **no YAML files** — all configuration arrives via env vars (ADR-0013)
  - All capture parameters come from this model: `audio.sample_rate`, `audio.channels`, `audio.format`, `processing.gain_db`, `stream.segment_duration_s` (default: 10s, US-R07)
- [x] Extend `build_recorder_spec()` in Controller's `container_spec.py` to inject `SILVASONIC_RECORDER_CONFIG_JSON`
  - Controller serializes `profile.config` (JSONB) via `json.dumps()` into the environment dict
  - This enables the Recorder to receive its full profile configuration without database access (ADR-0013, ADR-0016)
- [x] Apply profile parameters to `ffmpeg` subprocess pipeline:
  - `audio.sample_rate` → Raw stream sample rate
  - `audio.channels` → channel count
  - `audio.format` → bit depth / format string
  - `processing.gain_db` → input gain
  - `stream.segment_duration_s` → segment length
- [x] Unit tests: profile parsing, parameter mapping, segment duration override
- [x] Integration test: Recorder starts with injected profile and uses correct sample rate

---

## Phase 3: Generic USB Fallback & Auto-Enrollment

**Goal:** Unknown microphones are auto-enrolled with a safe generic profile, enabling immediate recording without user configuration.

**User Stories:** US-C10 (Unbekanntes Mikrofon funktioniert sofort)

### Tasks

- [x] Create `generic_usb.yml` seed profile in `services/controller/config/profiles/`:
  - 48 kHz, 1 ch, S16LE, Gain 0 dB, no highpass filter, no processing
  - No `match` criteria (used as fallback only, never auto-matched by VID/PID)
  - `is_system=true`, slug: `generic_usb`
- [x] Update `ProfileMatcher` / Reconciler: Score 0 → auto-assign `generic_usb` profile
  - Device gets `enrollment_status=enrolled`, `profile_slug=generic_usb`
  - Recorder starts immediately with safe defaults
  - User can later switch to a better profile via Web-Interface (v0.8.0+)
- [x] Unit tests: Score-0 auto-fallback assigns `generic_usb`, verify Recorder starts
- [x] Integration test: unknown USB device → `generic_usb` profile → Recorder spawns

---

## Phase 4: Dual Stream Architecture (Raw + Processed)

**Goal:** Recorder produces two simultaneous output streams from a single capture (ADR-0011, US-R03).

**User Stories:** US-R03 (Originalformat und Standardformat gleichzeitig)

### Tasks

- [x] Configure FFmpeg `-map` to produce two outputs simultaneously:
  - **Raw:** Native hardware sample rate & bit depth (direct copy)
  - **Processed:** Resampled to 48 kHz / S16LE by FFmpeg
- [x] Both streams write to separate `.buffer/` subdirectories via segment muxer
- [x] Both streams are promoted to `data/` independently via SegmentPromoter
- [x] Unit/Integration tests: verify dual output graph construction and promotion

---

## Phase 5: Watchdog & Auto-Recovery

**Goal:** Recorder detects pipeline failures and recovers automatically (US-R06).

**User Stories:** US-R02 (Aufnahme läuft immer weiter), US-R06 (Automatische Wiederherstellung)

### Tasks

- [ ] Implement `RecordingWatchdog` in `silvasonic/recorder/watchdog.py`
  - Monitor the FFmpeg process state and stream health
  - Detect: FFmpeg crash, hung process, or missing segments
  - On failure: restart FFmpeg subprocess with exponential backoff
- [ ] Integrate watchdog into `RecorderService.run()` lifecycle
- [ ] Report recording health via existing `_monitor_recording` health component
- [ ] Respect max retry limit (5 restarts, then give up — matches container restart policy)
- [ ] Unit tests: mock `ffmpeg` subprocess, verify failure detection and restart logic
- [ ] Integration test: simulate stream crash, verify automatic recovery

---

## Phase 6: Robustness & Isolation

**Goal:** Verify that the Recorder survives infrastructure failures and respects isolation (US-R02).

**User Stories:** US-R02 (Isolation von anderen Diensten)

### Tasks

- [ ] Test: Redis outage does not stop recording (heartbeats silently skipped)
- [ ] Test: Controller crash does not stop running Recorder
- [ ] Test: OOM scenario — verify Recorder is killed last (`oom_score_adj=-999`)
- [ ] Test: Read-only workspace mounts for non-Recorder services (ADR-0009 zero-trust)
- [ ] Verify segment files are valid WAV (header + data intact after promotion)
- [ ] Update Recorder README status table (mark implemented features)

---

## Out of Scope (Deferred)

| Item                                        | Target Version |
| ------------------------------------------- | -------------- |
| Live Opus stream (Recorder → Icecast)       | v0.9.0         |
| FLAC compression for upload                 | v0.6.0         |
| Processor service (ingestion + cleanup)     | v0.5.0         |
| Web-Interface profile editing               | v0.8.0         |
| I2S microphone support                      | post-v1.0.0    |

> **Note:** The Controller's Log Streaming (US-C09) and Hardening (crash recovery, multi-instance tests) are in [Milestone v0.3.0 Phase 5–6](milestone_0_3_0.md).
