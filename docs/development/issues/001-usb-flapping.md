# Issue 001: USB Flapping & Container Thrashing

**Status:** `closed`
**Priority:** 9/10 (Critical for core stability & data integrity. Immer lieber früher als später, ASAP fixen.)
**Labels:** `bug`, `architecture`, `robustness`
**Service(s) Affected:** `controller`

---

## 1. Description
A critical bug has been identified in the Controller's device management lifecycle, specifically related to unstable hardware connections ("USB Flapping"). 
When a device experiences a loose USB connection or power drop, it may momentarily disconnect and reconnect in an extremely short time span (milliseconds). Currently, this hardware instability triggers a cascade of synchronous, high-overhead operations in the software layer that leads to severe system degradation.

## 2. Context & Root Cause Analysis
The issue stems from a lack of debouncing (or "grace period" hysteresis) in the reconciliation loop.

* **Component:** `DeviceScanner` and `ReconciliationLoop` (`reconciler.py`)
* **Mechanism:** 
    1. **Lack of Polling Debounce:** The `DeviceScanner` polls `/proc/asound/cards` every 1 second (controlled by `RECONCILE_INTERVAL_S = 1.0` in `settings.py`). There is no caching or history mechanism. If a device drops for 50ms right when the scan occurs, it is instantly considered missing.
    2. **Immediate Offline Status update:** In `reconciler.py` (`ReconciliationLoop._mark_offline_devices()`), any device not present in the instantaneous scan result is immediately marked as `status = "offline"` in the database.
    3. **Synchronous Podman Teardown:** During the very same loop iteration, `DeviceStateEvaluator.evaluate()` notices the device is no longer eligible. `ContainerManager.sync_state()` then synchronously issues a `.stop_and_remove(timeout=10)` command to the corresponding Tier 2 container.
    4. **The Ping-Pong Effect:** The container teardown blocks the loop. In the next iteration, if the device is found again, it is marked as `online` and a new `.start()` is issued.

## 3. Impact / Consequences
* **Data Capture Integrity:** The hard stop explicitly contradicts the primary directive (Data Capture Integrity). The recording process (`ffmpeg`) is repeatedly interrupted, causing hundreds of truncated/corrupt audio snippets and massive data loss.
* **System Stability:** Continuously dropping and re-creating containers, namespaces, cgroups, and overlay filesystems consumes massive CPU limits resulting in Podman API thrashing and Out-Of-Memory (OOM) kills.
* **Hardware Wear:** Constant `UPDATE devices SET status='online|offline'` queries result in database locks and high I/O write wear on the SD card/NVMe.

## 4. Steps to Reproduce (If applicable)
1. Configure a `RECONCILE_INTERVAL_S` of `1.0`.
2. Connect a USB microphone, let it be enrolled, and wait for the `recorder` container to start.
3. Rapidly disconnect and reconnect the USB microphone to simulate a loose connection or power drop spanning milliseconds.
4. Observe the `controller` logs spamming container start/stop events and database updates.

## 5. Expected Behavior
The system should implement a grace period and wait an appropriate time (e.g., 3-5 seconds) before formally tearing down the container to account for transient USB flapping, without affecting instantaneous startups.

## 6. Proposed Solution
A hysteresis or debouncing logic must be introduced before escalating a missing device to an `offline` database state.

* **In-Memory Tracking:** The `ReconciliationLoop` should maintain an internal state (e.g., `_missing_devices: dict[str, int]`).
* **Grace Period Verification:** 
  * When a previously online device is missing from `current_ids` during a rescan, it is initially flagged as `missing` internally, incrementing a missed-scan counter.
  * Only when its counter reaches a predefined threshold (e.g., 3 consecutive missed scans representing ~3 seconds of continuous absence), is the device formally marked `offline` in the database, triggering the container teardown.
* **Instant Reconnects:** If a missing device reappears before the threshold is met, its counter is simply zeroed out. A "Start" event (going `online`) should remain instant, with zero debounce, to prioritize recording initiation.

## 7. Relevant Documentation Links
* [AGENTS.md](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md)
* [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md)
