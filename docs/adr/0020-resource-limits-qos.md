# ADR-0020: Resource Limits & QoS — Protecting Data Capture Integrity

> **Status:** Accepted • **Date:** 2026-02-21

## 1. Context & Problem

Silvasonic runs on a Raspberry Pi 5 with **4–8 GB RAM**. When Tier 2 analysis workers (BirdNET, BatDetect) perform TensorFlow/TFLite inference concurrently with the Recorder, they can exhaust system memory. The Linux **OOM Killer** then terminates processes to free memory — but it selects victims semi-randomly. In the worst case, it kills the **Recorder**, violating the paramount directive: **Data Capture Integrity**.

Without explicit resource constraints:

*   A single BirdNET inference batch can consume >1 GB RAM.
*   Two concurrent analysis workers + Recorder + database can exceed the 4 GB physical limit.
*   The OOM Killer has no awareness of Silvasonic's service priorities.

This is not a theoretical risk — it is the **expected failure mode** on a memory-constrained edge device running ML workloads.

## 2. Decision

**We chose:** Mandatory Podman resource limits on every Tier 2 container, combined with `oom_score_adj` to establish a QoS priority hierarchy.

### 2.1. Resource Budget

Every `Tier2ServiceSpec` **MUST** include `memory_limit` and `cpu_limit`. The Controller enforces these limits via `podman.containers.run()` parameters.

**Default Resource Budget (4 GB RPi 5):**

| Service       | `memory_limit` | `cpu_limit` | Rationale                                               |
| ------------- | -------------- | ----------- | ------------------------------------------------------- |
| **Recorder**  | `512m`         | `1.0`       | Low memory footprint (audio buffering only), 1 core max |
| **BirdNET**   | `1g`           | `1.0`       | TFLite inference requires ~600–900 MB, 1 core max       |
| **BatDetect** | `1g`           | `1.0`       | Similar ML inference workload                           |
| **Uploader**  | `256m`         | `0.5`       | FLAC compression + network I/O, low compute             |
| **Weather**   | `128m`         | `0.25`      | Lightweight API polling + DB writes                     |

> [!NOTE]
> These are **default values** embedded in the `Tier2ServiceSpec` definitions. They can be overridden via environment variables (e.g., `SILVASONIC_BIRDNET_MEMORY_LIMIT`) for hardware variants (8 GB RPi 5).

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
| **Expendable**   | `500`           | BirdNET, BatDetect, Weather | Optional features — safe to kill and restart.         |
| **Low Priority** | `250`           | Uploader                    | Important but can recover — retry after restart.      |

> [!IMPORTANT]
> The Recorder MUST always set `oom_score_adj=-999`. This is the **last line of defense** for Data Capture Integrity. Even if resource limits are misconfigured or a bug causes a memory leak, the kernel will kill every other container before touching the Recorder.

### 2.3. Podman Implementation

The Controller passes these parameters to `podman.containers.run()`:

```python
# Recorder — maximum OOM protection, bounded memory
container = podman.containers.run(
    image="silvasonic-recorder:latest",
    name="silvasonic-recorder-mic1",
    detach=True,
    mem_limit="512m",
    cpu_quota=100_000,       # 1.0 CPU (100% of one core)
    oom_score_adj=-999,      # Protected: last to be killed
    # ... other params (network, labels, mounts, etc.)
)

# BirdNET — expendable, bounded memory
container = podman.containers.run(
    image="silvasonic-birdnet:latest",
    name="silvasonic-birdnet",
    detach=True,
    mem_limit="1g",
    cpu_quota=100_000,       # 1.0 CPU
    oom_score_adj=500,       # Expendable: kill before Recorder
    # ... other params
)
```

### 2.4. Tier2ServiceSpec Integration

The `Tier2ServiceSpec` Pydantic model (see [TIER2_ROADMAP.md](../../TIER2_ROADMAP.md) Phase 2) MUST include resource limit fields:

```python
class Tier2ServiceSpec(BaseModel):
    # ... existing fields (image, name, labels, env, mounts, etc.)

    # Resource Limits (ADR-0020)
    memory_limit: str          # e.g., "512m", "1g"
    cpu_limit: float           # e.g., 1.0, 0.5
    oom_score_adj: int         # e.g., -999, 500
```

The `container_manager.start()` method MUST pass these fields to `podman.containers.run()`. Omitting resource limits is a **code review rejection criterion**.

## 3. Options Considered

*   **No limits (trust the workloads):** Rejected. ML workloads are unpredictable; a single inference batch can exhaust available RAM. The OOM Killer will eventually fire on a 4 GB device — the only question is *which* process it kills.
*   **Systemd-level cgroup limits (per-user slice):** Rejected. Podman already uses cgroups v2 under the hood. Setting limits per-container via `podman run` is more granular, auditable, and consistent with the existing Tier 2 management pattern.
*   **Memory limits only (no `oom_score_adj`):** Rejected. Limits alone prevent *individual* containers from overallocating, but they don't protect the Recorder if *total* system memory is exhausted (e.g., kernel buffers, Tier 1 services, or a misconfigured limit). `oom_score_adj` is the defense-in-depth layer.
*   **`oom_score_adj=-1000` for Recorder:** Rejected. `-1000` is "unkillable" — the kernel will deadlock rather than free memory. `-999` provides near-maximum protection while permitting the kernel to function correctly under extreme conditions.

## 4. Consequences

*   **Positive:**
    *   **Data Capture Integrity guaranteed:** The Recorder is the last container the OOM Killer targets.
    *   **Predictable behavior:** Each container has a known memory ceiling — no surprise OOMs that take down unrelated services.
    *   **Defense in depth:** Two independent mechanisms protect the Recorder — resource limits (prevent overallocation) + OOM priority (protect when limits aren't enough).
    *   **Scalable to hardware variants:** Resource budgets are configurable per device class (4 GB vs. 8 GB).
*   **Negative:**
    *   Analysis workers **will be killed** if they exceed their memory limit. TensorFlow models must be sized appropriately, or batch sizes reduced.
    *   CPU limits may slow inference. On a 4-core RPi 5 with 1.0 CPU per worker, two concurrent workers use 50% of CPU capacity. This is intentional — the Recorder and Tier 1 services need headroom.
    *   Resource budgets must be monitored and tuned in production. Initial defaults are estimates based on typical BirdNET/BatDetect workloads.

## 5. References

*   [ADR-0013: Tier 2 Container Management](0013-tier2-container-management.md) — Container lifecycle, `Tier2ServiceSpec`
*   [TIER2_ROADMAP.md](../../TIER2_ROADMAP.md) — Implementation phases
*   [VISION.md §Design Principles](../../VISION.md) — Resource Isolation principle
*   Linux kernel documentation: [OOM Killer](https://www.kernel.org/doc/html/latest/admin-guide/mm/concepts.html)
*   Podman documentation: [Resource constraints](https://docs.podman.io/en/latest/markdown/podman-run.1.html)
