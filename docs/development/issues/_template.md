# [Issue Title]

**Status:** `open` | `in-progress` | `resolved`
**Priority:** [1-10] (10 = highest, must fix for MVP)
**Labels:** `bug` | `enhancement` | `tech-debt` | `architecture`
**Service(s) Affected:** `controller` | `recorder` | `processor` | `...`

---

## 1. Description
A concise description of the bug, missing feature, or architectural issue. What is failing or could be improved?

## 2. Context & Root Cause Analysis
Explain *why* this is happening. Point to the specific lines of code, architectural decisions, or hardware behaviors (e.g., ALSA, Podman, Redis) that cause the issue. 

* **Component:** (e.g., `DeviceScanner`, `ReconciliationLoop`)
* **Mechanism:** (e.g., Immediate 1s polling without debounce)

## 3. Impact / Consequences
Describe the real-world impact of this issue on a field device (Raspberry Pi 5).
* **Data Capture Integrity:** Does it interrupt recordings?
* **System Stability:** Are there OOM risks, CPU spikes, or `podman` API thrashing?
* **Hardware Wear:** Does it cause excessive I/O on the SD card/NVMe?

## 4. Steps to Reproduce (If applicable)
1. 
2. 
3. 

## 5. Expected Behavior
What *should* happen instead? (e.g., "The system should wait 3 seconds before tearing down the container to account for USB flapping.")

## 6. Proposed Solution
Detail the technical approach to fix the issue. 
* Should we add an in-memory counter? 
* Do we need to modify a database schema?
* Does this require a new Architecture Decision Record (ADR)?

## 7. Relevant Documentation Links
* [AGENTS.md](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md)
* [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md)
* ADRs: ...
