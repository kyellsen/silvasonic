# ADR-0020: Resource Limits & QoS — Protecting Data Capture Integrity

> **Status:** Accepted • **Date:** 2026-02-21

## 1. Context & Problem

Silvasonic runs on a Raspberry Pi 5 with **4–8 GB RAM**. When Tier 2 analysis workers (BirdNET, BatDetect) perform TensorFlow/TFLite inference concurrently with the Recorder, they can exhaust system memory. The Linux **OOM Killer** then terminates processes to free memory — but it selects victims semi-randomly. In the worst case, it kills the **Recorder**, violating the paramount directive: **Data Capture Integrity**.

This is not a theoretical risk — it is the **expected failure mode** on a memory-constrained edge device running ML workloads.

## 2. Decision

**We chose:** Mandatory Podman resource limits on every Tier 2 container, combined with `oom_score_adj` to establish a QoS priority hierarchy.

### 2.1. Resource Budget

Every `Tier2ServiceSpec` **MUST** include `memory_limit` and `cpu_limit`. The Controller enforces these limits via `podman.containers.run()` parameters (see [ADR-0013](0013-tier2-container-management.md)).

**Default Resource Budget (4 GB RPi 5):**

| Service       | `memory_limit` | `cpu_limit` | Rationale                                               |
| ------------- | -------------- | ----------- | ------------------------------------------------------- |
| **Recorder**  | `512m`         | `1.0`       | Low memory footprint (audio buffering only), 1 core max |
| **BirdNET**   | `1g`           | `1.0`       | TFLite inference requires ~600–900 MB, 1 core max       |
| **BatDetect** | `1g`           | `1.0`       | Similar ML inference workload                           |
| **Uploader**  | `256m`         | `0.5`       | FLAC compression + network I/O, low compute             |
| **Weather**   | `128m`         | `0.25`      | Lightweight API polling + DB writes                     |

> [!NOTE]
> These are **default values** embedded in the `Tier2ServiceSpec` definitions. They can be overridden via environment variables for hardware variants (8 GB RPi 5).

**System-Wide Budget (4 GB device):**

| Category                                            | Reserved RAM |
| --------------------------------------------------- | ------------ |
| Tier 1 Infrastructure (DB, Redis, Controller, etc.) | ~1.5 GB      |
| Recorder (×1–2)                                     | ~0.5–1.0 GB  |
| Analysis Workers (BirdNET + BatDetect)              | ~2.0 GB      |
| OS + kernel overhead                                | ~0.5 GB      |
| **Total**                                           | **~4.0 GB**  |

### 2.2. OOM Priority Hierarchy

The `oom_score_adj` parameter tells the Linux kernel which processes to kill first when memory is exhausted. Range: -1000 (never kill) to +1000 (kill first).

| OOM Priority     | `oom_score_adj` | Services                    | Rationale                                             |
| ---------------- | --------------- | --------------------------- | ----------------------------------------------------- |
| **Protected**    | `-999`          | Recorder                    | Data Capture Integrity is paramount. Never kill.      |
| **Default**      | `0`             | Tier 1 infrastructure       | Managed by Compose/Quadlets, default kernel behavior. |
| **Low Priority** | `250`           | Uploader                    | Important but can recover — retry after restart.      |
| **Expendable**   | `500`           | BirdNET, BatDetect, Weather | Optional features — safe to kill and restart.         |

> [!IMPORTANT]
> The Recorder MUST always set `oom_score_adj=-999`. This is the **last line of defense** for Data Capture Integrity. Even if resource limits are misconfigured or a bug causes a memory leak, the kernel will kill every other container before touching the Recorder.

## 3. Options Considered

*   **No limits (trust the workloads):** Rejected. ML workloads are unpredictable; a single inference batch can exhaust available RAM.
*   **Systemd-level cgroup limits (per-user slice):** Rejected. Podman already uses cgroups v2 under the hood. Per-container limits via `podman run` are more granular and auditable.
*   **Memory limits only (no `oom_score_adj`):** Rejected. Limits alone don't protect the Recorder if *total* system memory is exhausted. `oom_score_adj` is the defense-in-depth layer.
*   **`oom_score_adj=-1000` for Recorder:** Rejected. `-1000` is "unkillable" — the kernel will deadlock rather than free memory. `-999` provides near-maximum protection while permitting the kernel to function correctly.

## 4. Consequences

*   **Positive:**
    *   **Data Capture Integrity guaranteed:** The Recorder is the last container the OOM Killer targets.
    *   **Predictable behavior:** Each container has a known memory ceiling.
    *   **Defense in depth:** Two independent mechanisms — resource limits + OOM priority.
    *   **Scalable to hardware variants:** Resource budgets are configurable per device class.
*   **Negative:**
    *   Analysis workers **will be killed** if they exceed their memory limit.
    *   CPU limits may slow inference on a 4-core RPi 5.
    *   Resource budgets must be monitored and tuned in production.

## 5. References

*   [ADR-0013: Tier 2 Container Management](0013-tier2-container-management.md) — Container lifecycle, `Tier2ServiceSpec`
*   [VISION.md §Design Principles](../../VISION.md) — Resource Isolation principle
