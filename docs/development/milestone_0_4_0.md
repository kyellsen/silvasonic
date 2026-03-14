# Milestone v0.4.0 — Audio Recording (Dual Stream)

> **Target:** v0.4.0 — Recorder captures audio from USB microphones: Python/C pipeline (`sounddevice`+`soundfile`), segmented WAV output, Dual Stream (Raw + Processed), Watchdog & Auto-Recovery
>
> **References:** [ADR-0011](../adr/0011-audio-recording-strategy.md), [ADR-0013](../adr/0013-tier2-container-management.md), [ADR-0016](../adr/0016-hybrid-yaml-db-profiles.md), [ADR-0020](../adr/0020-resource-limits-qos.md), [Recorder README](../../services/recorder/README.md)
>
> **User Stories:** [US-R01](../user_stories/recorder.md#us-r01), [US-R02](../user_stories/recorder.md#us-r02), [US-R03](../user_stories/recorder.md#us-r03), [US-R06](../user_stories/recorder.md#us-r06), [US-R07](../user_stories/recorder.md#us-r07)

---

## Phase 1: Python Audio Pipeline & Single-Stream Capture

**Goal:** Recorder captures audio from an ALSA device using `sounddevice` and writes segmented WAV files using `soundfile`.

### Tasks

- [ ] Add `sounddevice`, `soundfile`, and `soxr` as dependencies to `services/recorder/pyproject.toml`
- [ ] Add `libportaudio2`, `libsndfile1`, and `libsoxr-dev` as system dependencies in Recorder `Containerfile`
- [ ] Create `silvasonic/recorder/pipeline.py` — Audio pipeline builder
  - Use `sounddevice.InputStream` with callback for non-blocking capture
  - Input: ALSA device (e.g., `hw:1,0`)
  - Output: segmented WAV files in `.buffer/raw/` using `soundfile.SoundFile`
  - Segment naming convention: `{ISO-timestamp}_{duration}s.wav`
- [ ] Implement `.buffer/` → `data/` file promotion logic
  - On segment close: atomically move from `.buffer/raw/` to `data/raw/`
  - Ensures Processor only sees complete files
- [ ] Create workspace directory structure on startup:
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
- [ ] Read `SILVASONIC_RECORDER_DEVICE` from environment (ALSA device ID, e.g. `hw:1,0`)
- [ ] Parse `SILVASONIC_RECORDER_CONFIG_JSON` into a Pydantic model at startup
  - The Controller serializes the `config` JSONB column from the `microphone_profiles` table and passes it as a single environment variable (ADR-0016)
  - The Recorder has **no database access** and **no YAML files** — all configuration arrives via env vars (ADR-0013)
  - All capture parameters come from this model: `audio.sample_rate`, `audio.channels`, `audio.format`, `processing.gain_db`, `stream.segment_duration_s` (default: 10s, US-R07)
- [ ] Extend `build_recorder_spec()` in Controller's `container_spec.py` to inject `SILVASONIC_RECORDER_CONFIG_JSON`
  - Controller serializes `profile.config` (JSONB) via `json.dumps()` into the environment dict
  - This enables the Recorder to receive its full profile configuration without database access (ADR-0013, ADR-0016)
- [ ] Apply profile parameters to `sounddevice` / `soundfile` pipeline:
  - `audio.sample_rate` → Raw stream sample rate
  - `audio.channels` → channel count
  - `audio.format` → bit depth / format string
  - `processing.gain_db` → input gain
  - `stream.segment_duration_s` → segment length
- [ ] Unit tests: pipeline construction, segment naming, buffer-to-data promotion, profile parsing and parameter mapping
- [ ] Integration test: start Recorder with mock audio device, verify WAV files appear

---

## Phase 2: Dual Stream Architecture (Raw + Processed)

**Goal:** Recorder produces two simultaneous output streams from a single capture (ADR-0011, US-R03).

### Tasks

- [ ] Extend audio callback to produce two outputs:
  - **Raw:** Native hardware sample rate & bit depth (direct write to `soundfile`)
  - **Processed:** Resampled to 48 kHz, 16-bit (using `soxr.resample`)
- [ ] Both streams write to separate `.buffer/` subdirectories
- [ ] Both streams are promoted to `data/` independently
- [ ] Unit tests: verify dual output graph construction
- [ ] Integration test: capture produces files in both `data/raw/` and `data/processed/`

---

## Phase 3: Watchdog & Auto-Recovery

**Goal:** Recorder detects pipeline failures and recovers automatically (US-R06).

### Tasks

- [ ] Implement `RecordingWatchdog` in `silvasonic/recorder/watchdog.py`
  - Monitor the audio stream state and ring buffer
  - Detect: stream overflow (xruns), dead stream (no callbacks for X seconds)
  - On failure: restart pipeline with exponential backoff
- [ ] Integrate watchdog into `RecorderService.run()` lifecycle
- [ ] Report recording health via existing `_monitor_recording` health component
- [ ] Respect max retry limit (5 restarts, then give up — matches container restart policy)
- [ ] Unit tests: mock `sounddevice`, verify failure detection and restart logic
- [ ] Integration test: simulate stream crash, verify automatic recovery

---

## Phase 4: Robustness & Isolation

**Goal:** Verify that the Recorder survives infrastructure failures and respects isolation (US-R02).

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
