# <Service Name>

> **Status:** Planned (vX.Y.0) · **Tier:** <1 | 2> · **Instances:** <Single | Multi-instance: one per …>

<!-- One-liner: what this service IS and WHY it matters. -->

---

## 1. The Problem / The Gap

*   Why does this service need to exist?
*   What capability is missing without it?

## 2. User Benefit

*   What does the user gain when this service is running?
*   What workflows become possible?

## 3. Core Responsibilities

What does this service own? Describe the data flow.

### Inputs

*   What data/signals does this service consume?
*   Where does it read from (filesystem path, DB table, Redis channel, network)?

### Processing

*   What is the core logic / transformation?

### Outputs

*   What does this service produce (files, DB rows, streams, events)?
*   What DB tables does it write to?

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                     |
| ---------------- | -------------------------------- |
| **Immutable**    | <Yes / No> (ADR-0019)            |
| **DB Access**    | <Yes / No / Read-Only>           |
| **Concurrency**  | <Event Loop / Queue Worker / …>  |
| **State**        | <Stateless / Stateful>           |
| **Privileges**   | <Rootless / Privileged (reason)> |
| **Resources**    | <Low / Medium / High (why)>      |
| **QoS Priority** | <oom_score_adj value> (ADR-0020) |

## 5. Configuration & Environment

<!-- Known environment variables, volume mounts, ports, and device access. -->

| Variable / Mount         | Description          | Default / Example |
| ------------------------ | -------------------- | ----------------- |
| `SILVASONIC_<NAME>_PORT` | Health endpoint port | `9500`            |
| `/mnt/data/<path>:ro`    | …                    | —                 |

## 6. Technology Stack

<!-- Key libraries, models, or external dependencies beyond silvasonic-core. -->

*   **ML Model:** e.g., BatDetect2, BirdNET
*   **Audio:** e.g., `soundfile`, `numpy`
*   **External APIs:** e.g., OpenMeteo

## 7. Open Questions & Future Ideas

<!-- Unresolved design decisions, alternative approaches, or post-MVP enhancements. -->

*   …

## 8. Out of Scope

What does this service explicitly **NOT** do?

*   **Does NOT** …

## 9. References

*   [ADR-XXXX](../adr/XXXX-title.md) — …
*   [Glossary](../glossary.md) — canonical definition
*   [VISION.md](../../VISION.md) — roadmap entry
