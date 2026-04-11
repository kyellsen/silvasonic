# [BUG] 006: Controller adopts unhealthy Recorder containers and never self-heals them

> **Status:** `closed`
>
> **Priority:** 8
>
> **Labels:** `bug` | `architecture`
>
> **Service(s) Affected:** `controller` | `recorder`

---

## 1. Description
*Update (v0.8.0): Both the Recorder-side fail-fast and the Controller-side health-aware reconciliation are now implemented and verified by system tests.*

Originally, the Controller reconciled Recorder containers based on container presence and config hash only, but not on functional recording health. A Recorder container could remain running while not recording any audio, and the Controller would continue to adopt it as healthy desired state.

This created a silent failure mode: the system appeared operational at the container layer, but Data Capture Integrity was already lost.

## 2. Context & Root Cause Analysis
The current reconciliation logic in `services/controller/src/silvasonic/controller/container_manager.py` only compares desired vs. actual containers using:
- container name
- config drift via `io.silvasonic.config_hash`

It does **not** inspect Recorder health status or recording activity.

At the same time, `services/recorder/src/silvasonic/recorder/__main__.py` still allows a Recorder to remain alive in a non-recording state:
- If device validation fails, it sets health to false and then waits for shutdown instead of exiting with an error.
- This means Podman still sees a running container.
- The Controller then sees a matching desired container and performs no corrective action.

* **Component:** `ContainerManager.sync_state`, `RecorderService.run`
* **Mechanism:** Controller reconciliation is based on container presence/config only, while Recorder device-validation failure does not terminate the container.

## 3. Impact / Consequences
* **Data Capture Integrity:** High risk. Recording may be completely inactive while the system appears nominal.
* **System Stability:** Silent degraded state; no automatic recovery path is triggered.
* **Hardware Wear:** Low direct hardware wear, but repeated manual intervention becomes necessary.

This is a real MVP issue because a field unit can stop capturing audio without triggering container recreation.

## 4. Steps to Reproduce (If applicable)
1. Start a Recorder with an ALSA device that is temporarily unavailable or invalid.
2. FFmpeg will fail to start → Watchdog restarts → Container restart → Reconciliation.
3. ~~Previously: `RecorderService._validate_device()` would fail and the Recorder would wait idle indefinitely.~~ **RESOLVED:** `_validate_device()` was removed; the Recorder now always attempts to start FFmpeg directly, engaging the multi-level recovery chain.
4. Observe that the Controller continues to adopt the container because name and config hash still match.

## 5. Expected Behavior
A Recorder that is not actually able to record should not remain indefinitely adopted by the Controller as healthy desired state.

Either:
- the Recorder should exit with a failure state when it cannot start recording, or
- the Controller should actively detect unhealthy/non-recording Recorder containers and recreate them.

## 6. Proposed Solution
Implement one or both of the following:

1. **Recorder-side fail-fast** ✅ **RESOLVED**
   - `_validate_device()` was removed. The Recorder always starts FFmpeg directly.
   - If FFmpeg fails, the Watchdog restarts it (Level 1). If exhausted, the container exits and Podman `restart: on-failure` takes over (Level 2).

2. **Controller-side health-aware reconciliation** ✅ **RESOLVED**
   - The `ReconciliationLoop._reconcile_once()` now evaluates heartbeat freshness
     via Redis (`silvasonic:status:<device_id>`) before executing `sync_state`.
   - Containers with missing, stale (>45s), or error-status heartbeats are
     actively evicted via `ContainerManager.stop_and_remove()` and excluded
     from the `actual` list, causing `sync_state` to recreate them.
   - System test: `tests/system/test_controller_health_reconciliation.py`
     validates the full zombie-detection-and-replacement cycle.

## 7. Relevant Documentation Links
* [AGENTS.md](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md)
* [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md)
* [services/controller/README.md](https://github.com/kyellsen/silvasonic/blob/main/services/controller/README.md)
* [services/recorder/README.md](https://github.com/kyellsen/silvasonic/blob/main/services/recorder/README.md)
* [docs/user_stories/controller.md](../../user_stories/controller.md)
* [docs/user_stories/recorder.md](../../user_stories/recorder.md)
* ADRs:
  * [ADR-0013: Tier 2 Container Management](../../adr/0013-tier2-container-management.md)
  * [ADR-0019: Unified Service Infrastructure](../../adr/0019-unified-service-infrastructure.md)
