# [BUG] `upsert_device()` fails to update volatile hardware config 

**Status:** `open`
**Priority:** 10/10 (Crash loop and total loss of recording after simple unplug/replug. Höchste Prio, sofort fixen.)
**Labels:** `bug`
**Service(s) Affected:** `controller`

---

## 1. Description
When a known USB microphone is detected by the `DeviceScanner`, the database persistence layer (`upsert_device()`) updates the system-level fields `status` and `last_seen`, but ignores the JSON `config` field containing volatile hardware state such as the current `alsa_card_index` and `alsa_device`. This causes the database to drift from the actual physical hardware state on the host.

## 2. Context & Root Cause Analysis
In `silvasonic/controller/device_repository.py:upsert_device()`, the `if existing is not None:` block bypasses any update to `existing.config`.

* **Component:** `upsert_device()` in `device_repository.py`.
* **Mechanism:** 
  The `device.name` (stable device ID) is often built from the `vendor-product-port` fallback if no serial number is present. 
  When the device is hotplugged rapidly on the same port, the stable ID stays the same, so `existing is not None` evaluates to `True`. However, if the Linux Kernel (ALSA) assigns a new ALSA index (e.g., from `hw:1,0` to `hw:2,0`), this new index is accurately captured in `DeviceInfo`, but never written back to `Device.config` in PostgreSQL.

## 3. Impact / Consequences
If the ALSA index drifts:
* **Data Capture Integrity:** The Recorder container will crash loop because the Reconciler passes the stale ALSA path (`device.config.get("alsa_device")` via `build_recorder_spec`) to Podman exactly as it was during the first insertion.
* **System Stability:** Endless container restarts cause CPU spikes, needless Podman API interactions, and log bloat, reducing the overall reliability of the deployment.
* **Loss of Recording:** Sound recording for the affected node stops entirely until manually fixed or the device is rebooted.

## 4. Steps to Reproduce
1. Plug in a USB microphone (simulating initial setup and enrollment, getting ALSA index e.g., `hw:1,0`).
2. Simulate ALSA index drift: Unplug the mic, plug in something else (or rely on Kernel allocation delays) to take `hw:1,0`, then plug the mic back into the original port so it gets `hw:2,0`.
3. The Reconciler scans and matches the device again, marking it online.
4. The Reconciler spawns the Recorder container passing `SILVASONIC_RECORDER_DEVICE=hw:1,0`.
5. The container script/ffmpeg crashes because `hw:1,0` is incorrect.

## 5. Expected Behavior
Whenever a device update is triggered in `upsert_device()`, the `config` field must overwrite volatile ALSA properties (`alsa_card_index`, `alsa_name`, `alsa_device`) with the latest values from the `DeviceInfo` scan object to ensure the database stays perfectly synced with the true hardware state.

## 6. Proposed Solution
Update `upsert_device()` (in `silvasonic/controller/device_repository.py`) to pull the latest volatile fields from the `device_info` object into `existing.config`.
Because SQLAlchemy requires an explicitly new dictionary assignment to trigger a JSON field update:
```python
if existing is not None:
    existing.status = "online"
    existing.last_seen = datetime.now(UTC)
    
    # Write updated volatile hardware info
    updated_config = dict(existing.config) if existing.config else {}
    updated_config.update({
        "alsa_card_index": device_info.alsa_card_index,
        "alsa_device": device_info.alsa_device,
        "alsa_name": device_info.alsa_name,
    })
    existing.config = updated_config
```

## 7. Relevant Documentation Links
* [AGENTS.md](../../AGENTS.md)
* [VISION.md](../../VISION.md)
* [ADR-0013: Tier 2 Container Management](../../adr/0013-tier2-container-management.md)
