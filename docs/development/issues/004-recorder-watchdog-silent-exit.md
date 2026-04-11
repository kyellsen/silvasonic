# [BUG] 004: Recorder watchdog gives up without causing a container-level failure

> **Status:** `closed`
>
> **Priority:** 10
>
> **Labels:** `bug`, `architecture`
>
> **Service(s) Affected:** `recorder`

---

## 1. Description
*Update (v0.8.0): The core codebase logic for this issue is fixed. The watchdog now raises a `RuntimeError` upon exhaustion, causing the container to crash with exit code 1. This remaining work is to provide a behavioral system-level test to guarantee this contract.*

Originally, when the Recorder watchdog exhausted its restart budget (`max_restarts`), it gracefully exited the Python process with code 0 instead of failing hard. This incorrectly bypassed the Level 2 recovery mechanism (Podman's `restart: on-failure`).

## 2. Context & Root Cause Analysis
The failure occurred due to the watchdog setting a flag and breaking out of its evaluation loop rather than raising an exception. Because no exception propagated to `SilvaService._main()`, the Python interpreter exited with 0 and no dying-gasp heartbeat was published.

This has been resolved in `RecordingWatchdog.watch` by explicitly raising a `RuntimeError` when restart budgets are exhausted. The exception successfully propagates up, forcing a container crash.

## 3. Impact / Consequences
Without a behavioral regression test, this critical recovery path remains functionally invisible to CI. If a future refactoring accidentally catches the exception or returns cleanly, the silent-exit bug could regress unobserved, compromising Data Capture Integrity.

## 4. Steps to Reproduce (In Test)
1. Force repeated FFmpeg startup or runtime failures (by supplying a mock recording source that instantly crashes).
2. Allow the watchdog to attempt restarts and consume the budget.
3. Assert that the container exits with a non-zero code.

## 5. Expected Behavior
The system test `test_recorder_watchdog_recovery.py` runs a recorder container, forces recurring FFmpeg crashes, and asserts that the container explicitly exits with an error code rather than hanging or returning exit code 0.

## 6. Proposed Solution
**Implementation Plan:**
1. Author `tests/system/test_recorder_watchdog_recovery.py`
2. Validate the test in the `just test-system` pipeline.
3. Close the issue.

## 7. Relevant Documentation Links
* [AGENTS.md](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md)
* [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md)
* [services/recorder/README.md](https://github.com/kyellsen/silvasonic/blob/main/services/recorder/README.md)
* ADRs:
  * [ADR-0013: Tier 2 Container Management](../../adr/0013-tier2-container-management.md)
  * [ADR-0019: Unified Service Infrastructure](../../adr/0019-unified-service-infrastructure.md)
