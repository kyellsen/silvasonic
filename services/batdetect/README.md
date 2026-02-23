# silvasonic-batdetect

> **Status:** Planned (v1.3.0) · **Tier:** 2 (Application, Managed by Controller) · **Instances:** Scalable

**TO-BE:** BatDetect is a specialized inference engine targeting ultrasonic bat echolocation calls, running locally on the Raspberry Pi 5 against high-sample-rate Raw WAV segments.

---

## The Problem / The Gap

*   **Ultrasonic Audio:** Bat calls (20kHz - 150kHz) require high sample rates (384kHz+) which generate massive files. Processing these at the edge is even more critical than bird calls to save bandwidth.
*   **Different Models:** BirdNET cannot handle ultrasonic bat calls; a dedicated model (like BatDetect2) is required.

## User Benefit

*   **Full Spectrum:** Makes Silvasonic a dual-purpose (Avian + Chiroptera) recording station.
*   **Edge Processing:** Avoids uploading terabytes of ultrasonic noise.

---

## Core Responsibilities

*   **Inference Loop:** Queries the database for unanalyzed, high-sample rate Raw WAV records.
*   **Execution:** Runs the model (e.g. BatDetect2) to pull out bounding boxes of bat calls.
*   **Database Update:** Inserts findings into the `detections` hypertable.

---

## Operational Constraints & Rules

| Aspect           | Value / Rule                                                                                      |
| ---------------- | ------------------------------------------------------------------------------------------------- |
| **Immutable**    | Yes.                                                                                              |
| **DB Access**    | **Yes** — Queries `recordings`, inserts into `detections`.                                        |
| **Concurrency**  | High CPU/RAM.                                                                                     |
| **State**        | Stateless — relies solely on the database and filesystem.                                         |
| **Privileges**   | Standard (rootless).                                                                              |
| **QoS Priority** | `oom_score_adj=500` (Expendable) — The OOM Killer will kill BatDetect first to save the Recorder. |

## Out of Scope

*   **Does NOT** manage its own lifecycle. The Controller provisions it.
