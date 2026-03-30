# Recorder watchdog gives up without causing a container-level failure

**Status:** `open`
**Priority:** 10
**Labels:** `bug`, `architecture`
**Service(s) Affected:** `recorder`

---

## 1. Description
When the Recorder watchdog exhausts its restart budget (`max_restarts`), it gives up and exits its watch loop. However, the service does not fail hard at the process level. Instead, the recorder container shuts down gracefully and the Python process exits with code 0. This weakens the intended multi-level recovery chain because Podman's `restart: on-failure` is never triggered when the exit code is 0.

## 2. Context & Root Cause Analysis
The failure occurs across three different architectural layers dealing with process execution and lifecycle management:

1. `services/recorder/src/silvasonic/recorder/watchdog.py`: Once `max_restarts` is exhausted, it sets `_giving_up = True` and uses `break` to exit the loop. It does not raise an exception.
2. `services/recorder/src/silvasonic/recorder/__main__.py`: `RecorderService.run()` awaits the watchdog. Because `watch()` returns normally, `run()` proceeds to the `finally` cleanup path, stopping the pipeline cleanly.
3. `packages/core/src/silvasonic/core/service.py`: `_main()` treats a clean return from `run()` as a successful, orderly shutdown (usually meant for SIGTERM). Because no exception propagates up, `service.py` exits cleanly without publishing a dying-gasp heartbeat, and the Python interpreter exits with `0`.

This means the documented recovery chain is currently broken at the transition from Level 1 to Level 2:
- Level 1: internal watchdog restart (Works)
- **Level 2: Podman `restart: on-failure` (FAILS due to clean exit)**
- Level 3: Controller recreation

* **Component:** `RecordingWatchdog.watch`, `RecorderService.run`, `SilvaService._main`
* **Mechanism:** Watchdog "giving up" is represented as a clean control-flow exit (exit 0) instead of an explicit service failure (exit 1+).

## 3. Impact / Consequences
This is a critical flaw for the MVP and field reliability.
* **Data Capture Integrity:** High risk. After repeated FFmpeg failures (e.g. from an unstable ALSA device), the recorder stops recovering automatically and the container shuts off. Recordings cease silently.
* **System Stability:** Recovery behavior becomes inconsistent with the architecture and documentation.
* **Hardware Wear:** Low direct wear, but continuous manual restarts reduce the systemic autonomy goal.

## 4. Steps to Reproduce (If applicable)
1. Force repeated FFmpeg startup or runtime failures (e.g., provide a nonexistent ALSA capture device or forcefully kill the `ffmpeg` subprocess multiple times).
2. Let the watchdog consume all configured restart attempts (`max_restarts`).
3. Observe that the watchdog logs `watchdog.giving_up`.
4. Run `podman ps -a` and observe that the container exited, but the exit reason is success (0) rather than an error code. `restart: on-failure` is completely bypassed.

## 5. Expected Behavior
When the watchdog can no longer recover the recording pipeline, the Recorder service should fail explicitly (throwing an exception or exiting with a non-zero code) so that Podman can correctly apply its container-level `restart: on-failure` policy.

## 6. Proposed Solution
After the watchdog gives up, convert this state into an explicit service failure.

**Implementation Plan:**
1. In `RecorderService.run` (`services/recorder/src/silvasonic/recorder/__main__.py`), after `await self._watchdog.watch(...)` returns, check `self._watchdog.is_giving_up`.
2. If `True`, raise a dedicated, explicitly named exception (e.g., `WatchdogGiveUpError("Watchdog exhausted max restarts and gave up.")`).
3. This exception will correctly bubble up into `SilvaService._main()`.
4. `_main()` will catch it, log the crash, trigger the `_publish_dying_gasp` heartbeat, and cause the Python process to exit with a non-zero exit code.
5. Podman's `restart: on-failure` will recognize the failure and execute a Level-2 container restart.

No database schema or config changes are required.

## 7. Relevant Documentation Links
* [AGENTS.md](../../AGENTS.md)
* [VISION.md](../../VISION.md)
* [services/recorder/README.md](../../../../services/recorder/README.md)
* ADRs:
  * [ADR-0013: Tier 2 Container Management](../../adr/0013-tier2-container-management.md)
  * [ADR-0019: Unified Service Infrastructure](../../adr/0019-unified-service-infrastructure.md)
