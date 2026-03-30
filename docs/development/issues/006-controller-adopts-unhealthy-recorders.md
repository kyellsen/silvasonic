# Controller adopts unhealthy Recorder containers and never self-heals them

**Status:** `open`
**Priority:** 8
**Labels:** `bug` | `architecture`
**Service(s) Affected:** `controller` | `recorder`

---

## 1. Description
The Controller currently reconciles Recorder containers based on container presence and config hash, but not on functional recording health. A Recorder container can remain running while not recording any audio, and the Controller will continue to adopt it as healthy desired state.

This creates a silent failure mode: the system appears operational at the container layer, but Data Capture Integrity is already lost.

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
2. Let `RecorderService._validate_device()` fail.
3. Observe that the Recorder process stays alive and waits for shutdown instead of exiting.
4. Observe that the Controller continues to adopt the container because name and config hash still match.

## 5. Expected Behavior
A Recorder that is not actually able to record should not remain indefinitely adopted by the Controller as healthy desired state.

Either:
- the Recorder should exit with a failure state when it cannot start recording, or
- the Controller should actively detect unhealthy/non-recording Recorder containers and recreate them.

## 6. Proposed Solution
Implement one or both of the following:

1. **Recorder-side fail-fast**
   - In `RecorderService.run`, if device validation fails or startup cannot establish recording, exit with an exception/non-zero status instead of waiting for shutdown.
   - This allows Podman `restart: on-failure` to engage.

2. **Controller-side health-aware reconciliation**
   - Extend Controller reconciliation to inspect Recorder health or a stronger runtime signal than container presence alone.
   - Possible mechanisms:
     - poll `/healthy` from managed containers
     - inspect health state from Podman if exposed
     - use a Redis heartbeat freshness check per Recorder instance
     - optionally define a label or metadata contract for “recording active”

No schema change is strictly required, but this may warrant an ADR or at least an architecture note because it changes the Controller’s reconciliation contract from “container exists” to “container is functionally healthy”.

## 7. Relevant Documentation Links
* [AGENTS.md](../../../AGENTS.md)
* [VISION.md](../../../VISION.md)
* [services/controller/README.md](../../../services/controller/README.md)
* [services/recorder/README.md](../../../services/recorder/README.md)
* [docs/user_stories/controller.md](../../user_stories/controller.md)
* [docs/user_stories/recorder.md](../../user_stories/recorder.md)
* ADRs:
  * [ADR-0013: Tier 2 Container Management](../../adr/0013-tier2-container-management.md)
  * [ADR-0019: Unified Service Infrastructure](../../adr/0019-unified-service-infrastructure.md)
