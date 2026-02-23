# silvasonic-birdnet

> **Status:** Planned (v1.1.0) · **Tier:** 2 (Application, Managed by Controller) · **Instances:** Scalable

**TO-BE:** BirdNET is the primary deep-learning inference engine on the Silvasonic platform. It runs pre-trained models on 48kHz Processed WAV segments to identify avian vocalizations locally on the Raspberry Pi 5.

---

## The Problem / The Gap

*   **Bandwidth Cost:** Sending months of audio to the cloud for analysis is expensive and slow.
*   **Instant Feedback:** Researchers need metadata (What sang today?) much faster than raw audio can be synced.

## User Benefit

*   **Edge AI:** Classifications happen on-device, minimizing bandwidth and latency.
*   **Rich Metadata:** Avian species detections are indexed into the TimescaleDB for instant querying over the Web-Interface.

---

## Core Responsibilities

*   **Inference Loop:** Queries the database for unanalyzed, processed WAV records.
*   **Execution:** Runs the BirdNET-Analyzer over the file.
*   **Database Update:** Inserts individual confidence scores into the `detections` hypertable for every bird call found.

---

## Operational Constraints & Rules

| Aspect           | Value / Rule                                                                                    |
| ---------------- | ----------------------------------------------------------------------------------------------- |
| **Immutable**    | Yes — config at startup.                                                                        |
| **DB Access**    | **Yes** — Queries `recordings`, inserts into `detections`.                                      |
| **Concurrency**  | High CPU/RAM. Often blocked on model loading or GPU/CPU inference.                              |
| **State**        | Stateless — relies solely on the database and filesystem.                                       |
| **Privileges**   | Standard (rootless).                                                                            |
| **QoS Priority** | `oom_score_adj=500` (Expendable) — The OOM Killer will kill BirdNET first to save the Recorder. |

## Out of Scope

*   **Does NOT** manage its own lifecycle. The Controller provisions it.
