# <Service Name>

> **Status:** Planned (vX.Y.0) · **Tier:** <1|2> · **Instances:** <Single | Multi-instance: one per …>

<!-- Short one-liner: what this service IS. -->

---

## 1. The Problem / The Gap

*   Why does this service need to exist?
*   What capability is missing without it?

## 2. User Benefit

*   What does the user gain when this service is running?

## 3. Core Responsibilities

### Inputs

*   What data/signals does this service consume?
*   Where does it read from (filesystem, DB table, Redis channel, network)?

### Processing

*   What is the core logic / transformation?

### Outputs

*   What does this service produce (files, DB rows, streams, events)?

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

## 5. Key ADRs & References

*   [ADR-XXXX](../adr/XXXX-title.md) — …
*   [Glossary](../glossary.md) — canonical definition
*   [VISION.md](../../VISION.md) — roadmap entry

## 6. Out of Scope

What does this service explicitly **NOT** do?

*   **Does NOT** …
